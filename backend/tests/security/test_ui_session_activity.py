from uuid import uuid4
from knowledge_ai.db import User
from knowledge_ai.governance.auth import passwords
from knowledge_ai.governance.audit import record_event
from knowledge_ai.profiles.models import Profile, ProfileGrant

def test_session_csrf_survives_new_tab_and_rejects_cross_origin(client, db):
    response=client.post('/api/auth/login',json={'username':'admin','password':'a-good-test-password'})
    token=response.json()['csrf_token']
    assert client.get('/api/auth/csrf').json()['csrf_token']==token
    assert client.get('/api/auth/csrf',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/auth/csrf',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.get('/api/auth/csrf').headers['cache-control']=='no-store'
    assert client.post('/api/users',json={'username':'new-user','password':'long-test-password','role':'reader'},headers={'X-CSRF-Token':token}).status_code==201
    assert client.post('/api/auth/logout').status_code==403

def test_read_grant_activity_excludes_private_events(client,db):
    with db.sessions() as s:
        owner=User(username='event-owner',role='owner',password_hash=passwords.hash('long-test-password'))
        reader=User(username='event-reader',role='reader',password_hash=passwords.hash('long-test-password'))
        s.add_all([owner,reader]);s.flush()
        p=Profile(name='Scoped test profile',kind='product',owner_id=owner.id);s.add(p);s.flush()
        s.add(ProfileGrant(profile_id=p.id,user_id=reader.id,read=True,contribute=False))
        record_event(s,owner.id,'candidate_edited',p.id,{'private':'secret draft'})
        record_event(s,owner.id,'publication_activated',p.id,{'generation_id':'safe','private':'must not leak'})
        record_event(s,owner.id,'candidate_edited',uuid4(),{'private':'unrelated'})
        s.commit()
    client.post('/api/auth/login',json={'username':'event-reader','password':'long-test-password'})
    result=client.get('/api/activity')
    assert result.status_code==200
    assert [e['action'] for e in result.json()]==['publication_activated']
    assert result.json()[0]['details']=={}
    client.post('/api/auth/login',json={'username':'event-owner','password':'long-test-password'})
    assert len(client.get('/api/activity').json())==2
