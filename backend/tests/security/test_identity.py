from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from knowledge_ai.app import create_app
from knowledge_ai.db import AuthSession, AuditEvent, User
from knowledge_ai.settings import Settings
from knowledge_ai.governance.policy import Actor, authorize

def login(client):
    return client.post('/api/auth/login', json={'username':'admin','password':'a-good-test-password'})

def test_anonymous_cannot_create_profile(client):
    assert client.post('/api/profiles', json={'name':'Product A','kind':'product'}).status_code == 401

def test_invalid_session(client):
    client.cookies.set('knowledge_ai_session', 'forged')
    assert client.get('/api/auth/me').status_code == 401

def test_login_logout_csrf_and_audit(client, db):
    response = login(client)
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/api/auth/me').json()['role'] == 'admin'
    assert client.post('/api/auth/logout').status_code == 403
    assert client.post('/api/auth/logout', headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert client.post('/api/auth/logout', headers={'X-CSRF-Token':response.json()['csrf_token']}).status_code == 204
    assert client.get('/api/auth/me').status_code == 401
    with db.sessions() as session:
        assert list(session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at))) == ['login','logout']
        assert session.scalar(select(User)).password_hash.startswith('$argon2')
        assert session.scalar(select(AuthSession)) is None

def test_expired_session(client, db):
    login(client)
    with db.sessions() as session:
        session.scalar(select(AuthSession)).expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        session.commit()
    assert client.get('/api/auth/me').status_code == 401

def test_disabled_user(client, db):
    login(client)
    with db.sessions() as session:
        session.scalar(select(User)).active = False
        session.commit()
    assert client.get('/api/auth/me').status_code == 401

def test_wrong_credentials_and_no_registration(client):
    assert client.post('/api/auth/login', json={'username':'admin','password':'wrong'}).status_code == 401
    assert client.post('/api/auth/register', json={}).status_code == 404
    assert login(client).status_code == 200

def test_cross_origin_login(client):
    assert client.post('/api/auth/login', json={'username':'admin','password':'a-good-test-password'}, headers={'Origin':'https://evil.example'}).status_code == 403

def test_health_readiness(client, settings):
    assert client.get('/health').status_code == 200
    assert client.get('/ready').status_code == 200
    settings.database_url = 'postgresql+psycopg://postgres:testpassword@127.0.0.1:1/unavailable'
    with TestClient(create_app(settings)) as broken:
        assert broken.get('/health').status_code == 200
        assert broken.get('/ready').status_code == 503

def test_missing_secret_rejected(monkeypatch):
    monkeypatch.delenv('KNOWLEDGE_AI_SIGNING_SECRET', raising=False)
    with pytest.raises(ValueError):
        Settings(database_url='postgresql+psycopg://localhost/test')
    with pytest.raises(ValueError):
        Settings(database_url='postgresql+psycopg://localhost/test', signing_secret='CHANGE_ME_secret_with_32_characters')

@pytest.mark.parametrize('role', ['admin','owner','contributor','reader'])
def test_scope_policy(role):
    profile = uuid4()
    actor = Actor(uuid4(), role)
    with pytest.raises(HTTPException):
        authorize(actor, 'review', profile)
    with pytest.raises(HTTPException):
        authorize(actor, 'unknown', profile)
    if role in {'admin','owner'}:
        authorize(Actor(actor.id, role, owned_profile_ids=frozenset({profile})), 'review', profile)
    if role != 'admin':
        with pytest.raises(HTTPException):
            authorize(actor, 'write', profile)
    authorize(Actor(actor.id, role, read_profile_ids=frozenset({profile})), 'read', profile)

def test_bootstrap_admin_is_local_and_duplicate_safe(db, monkeypatch):
    from knowledge_ai.cli import main
    monkeypatch.setattr('sys.argv', ['bootstrap-admin', 'local-owner'])
    monkeypatch.setattr('getpass.getpass', lambda _: 'local-bootstrap-password')
    main()
    with db.sessions() as session:
        user = session.scalar(select(User).where(User.username == 'local-owner'))
        assert user.role == 'admin'
        assert user.password_hash != 'local-bootstrap-password'
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == 'bootstrap_admin')).actor_id == user.id
    with pytest.raises(SystemExit):
        main()

def test_bootstrap_rejects_short_password(db, monkeypatch):
    from knowledge_ai.cli import main
    monkeypatch.setattr('sys.argv', ['bootstrap-admin', 'unsafe'])
    monkeypatch.setattr('getpass.getpass', lambda _: 'short')
    with pytest.raises(SystemExit):
        main()
    with db.sessions() as session:
        assert session.scalar(select(User).where(User.username == 'unsafe')) is None

def test_authenticated_profile_stub_enforces_csrf(client):
    response = login(client)
    assert client.post('/api/profiles', json={}).status_code == 403
    assert client.post('/api/profiles', json={}, headers={'X-CSRF-Token':response.json()['csrf_token']}).status_code == 501

def test_audit_rolls_back_with_transaction(db):
    from knowledge_ai.governance.audit import record_event
    with db.sessions() as session:
        actor = session.scalar(select(User))
        record_event(session, actor.id, 'test_rolled_back', details={'reason':'transaction'})
        session.flush()
        session.rollback()
    with db.sessions() as session:
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == 'test_rolled_back')) is None

@pytest.mark.parametrize('username,password', [('', 'valid-password'), ('x'*201, 'valid-password'), ('valid', 'x'*1025)])
def test_bootstrap_rejects_unusable_credentials(db, monkeypatch, username, password):
    from knowledge_ai.cli import main
    monkeypatch.setattr('sys.argv', ['bootstrap-admin', username])
    monkeypatch.setattr('getpass.getpass', lambda _: password)
    with pytest.raises(SystemExit):
        main()
    with db.sessions() as session:
        assert session.scalar(select(User).where(User.username == username)) is None
