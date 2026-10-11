import os
import pytest
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from knowledge_ai.app import create_app
from knowledge_ai.settings import Settings
from knowledge_ai.db import Database, User
from knowledge_ai.governance.auth import passwords

@pytest.fixture
def settings():
    return Settings(database_url=os.environ.get('KNOWLEDGE_AI_TEST_DATABASE_URL', 'postgresql+psycopg://postgres:testpassword@127.0.0.1:55432/knowledgeai_test'), signing_secret='test-only-secret-abcdefghijklmnopqrstuvwxyz')

@pytest.fixture
def db(settings, monkeypatch):
    assert settings.database_url.rsplit('/', 1)[-1].endswith('_test'), 'Refusing destructive setup outside test database'
    monkeypatch.setenv('KNOWLEDGE_AI_DATABASE_URL', settings.database_url)
    monkeypatch.setenv('KNOWLEDGE_AI_SIGNING_SECRET', settings.signing_secret)
    command.upgrade(Config('alembic.ini'), 'head')
    database = Database(settings.database_url)
    with database.sessions() as session:
        session.execute(text('TRUNCATE audit_events, auth_sessions, users CASCADE'))
        session.add(User(username='admin', password_hash=passwords.hash('a-good-test-password'), role='admin'))
        session.commit()
    yield database
    database.engine.dispose()

@pytest.fixture
def client(settings, db):
    with TestClient(create_app(settings)) as client:
        yield client
