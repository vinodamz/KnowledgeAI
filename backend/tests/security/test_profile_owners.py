from sqlalchemy import select
from knowledge_ai.db import User
from knowledge_ai.governance.auth import passwords


def setup(client, db):
    with db.sessions() as s:
        for name, role in [('owner-a','owner'),('owner-b','owner'),('reader','reader'),('contributor','contributor')]:
            s.add(User(username=name, role=role, password_hash=passwords.hash('a-good-test-password')))
        s.commit()
        ids = {u.username:str(u.id) for u in s.scalars(select(User))}
    authenticate(client, 'admin')
    return ids


def authenticate(client, name):
    r = client.post('/api/auth/login', json={'username':name,'password':'a-good-test-password'})
    client.headers['X-CSRF-Token'] = r.json()['csrf_token']


def test_owner_cannot_modify_another_profile(client, db):
    ids = setup(client, db)
    r = client.post('/api/profiles', json={'kind':'product','name':'A','owner_id':ids['owner-a']})
    assert r.status_code == 201
    pid = r.json()['id']
    authenticate(client, 'owner-b')
    assert client.patch(f'/api/profiles/{pid}', json={'name':'Changed'}).status_code == 403
    authenticate(client, 'owner-a')
    assert client.patch(f'/api/profiles/{pid}', json={'name':'Changed'}).status_code == 200


def test_grants_drafts_and_admin_users(client, db):
    ids = setup(client, db)
    pid = client.post('/api/profiles', json={'kind':'product','name':'A','owner_id':ids['owner-a']}).json()['id']
    version = client.post(f'/api/profiles/{pid}/versions', json={'label':'draft'}).json()
    assert client.put(f'/api/profiles/{pid}/grants/{ids["reader"]}', json={'read':True,'contribute':False}).status_code == 200
    authenticate(client,'reader')
    assert client.get(f'/api/profiles/{pid}').status_code == 200
    assert client.get(f'/api/profiles/{pid}/versions').json() == []
    assert client.get(f'/api/versions/{version["id"]}').status_code == 403
    assert client.post('/api/users', json={'username':'new','password':'a-good-test-password','role':'reader'}).status_code == 403
    authenticate(client,'admin')
    assert client.post('/api/users', json={'username':'new','password':'a-good-test-password','role':'reader'}).status_code == 201
    assert client.patch(f'/api/users/{ids["reader"]}', json={'active':False}).status_code == 200
    assert client.post('/api/auth/login', json={'username':'reader','password':'a-good-test-password'}).status_code == 401


def test_contributor_content_authority_is_not_profile_authority(client, db):
    from uuid import UUID
    from knowledge_ai.governance.policy import Actor, authorize
    from fastapi import HTTPException
    import pytest
    ids=setup(client,db)
    pid=client.post('/api/profiles',json={'kind':'product','name':'P','owner_id':ids['owner-a']}).json()['id']
    client.put(f'/api/profiles/{pid}/grants/{ids["contributor"]}',json={'read':True,'contribute':True})
    authenticate(client,'contributor')
    me=client.get('/api/auth/me').json()
    assert me['contribute_profile_ids']==[pid]
    assert client.patch(f'/api/profiles/{pid}',json={'name':'Changed'}).status_code==403
    assert client.post(f'/api/profiles/{pid}/versions',json={'label':'new'}).status_code==403
    actor=Actor(UUID(ids['contributor']),'contributor',contribute_profile_ids=frozenset({UUID(pid)}))
    authorize(actor,'write',UUID(pid))
    with pytest.raises(HTTPException): authorize(actor,'review',UUID(pid))
    authenticate(client,'admin')
    me=client.get('/api/auth/me').json()
    assert me['owned_profile_ids']==[]
    with pytest.raises(HTTPException): authorize(Actor(UUID(ids['admin']),'admin'),'review',UUID(pid))
    assert client.put(f'/api/profiles/{pid}/grants/{ids["contributor"]}',json={'read':False,'contribute':False}).status_code==200
    authenticate(client,'contributor')
    assert client.get(f'/api/profiles/{pid}').status_code==403


def test_owner_reassignment_updates_authority(client,db):
    ids=setup(client,db)
    pid=client.post('/api/profiles',json={'kind':'product','name':'P','owner_id':ids['owner-a']}).json()['id']
    assert client.patch(f'/api/profiles/{pid}',json={'owner_id':ids['owner-b']}).status_code==200
    authenticate(client,'owner-a')
    assert client.patch(f'/api/profiles/{pid}',json={'name':'Old owner'}).status_code==403
    authenticate(client,'owner-b')
    assert client.get('/api/auth/me').json()['owned_profile_ids']==[pid]
    assert client.patch(f'/api/profiles/{pid}',json={'owner_id':ids['owner-a']}).status_code==403
