from tests.integration.test_review_lifecycle import drafts
from tests.security.test_profile_owners import authenticate
import pytest

@pytest.mark.parametrize('username',['admin','owner-b','contributor','reader'])
def test_only_assigned_owner_can_review(client,db,tmp_path,username):
    p,v,c=drafts(client,db,tmp_path)
    authenticate(client,username)
    assert client.post(f"/api/candidates/{c['id']}/review",json={'expected_revision':1,'decision':'approve'}).status_code==403

def test_reassignment_keeps_attribution_and_rechecks_live_owner(client,db,tmp_path):
    from uuid import UUID
    from sqlalchemy import select
    from knowledge_ai.db import User
    from knowledge_ai.governance.policy import Actor
    from knowledge_ai.review.service import review_candidate
    from knowledge_ai.review.models import ReviewDecision
    from knowledge_ai.profiles.models import Profile
    from fastapi import HTTPException
    p,v,c=drafts(client,db,tmp_path)
    assert client.post(f"/api/candidates/{c['id']}/review",json={'expected_revision':1,'decision':'approve'}).status_code==200
    with db.sessions() as s:
        owner=s.scalar(select(User).where(User.username=='owner-a'));replacement=s.scalar(select(User).where(User.username=='owner-b'));oid=owner.id;rid=replacement.id
        actor=Actor(oid,'owner',frozenset({UUID(p)}))
        cached=s.get(Profile,UUID(p))
        with db.sessions() as second:
            second.get(Profile,UUID(p)).owner_id=rid;second.commit()
        with pytest.raises(HTTPException) as error:review_candidate(s,actor,UUID(c['id']),1,'reject','Changed owner')
        assert error.value.status_code==403
        s.rollback()
        assert s.scalar(select(ReviewDecision)).actor_id==oid
    authenticate(client,'owner-b')
    assert client.post(f"/api/candidates/{c['id']}/review",json={'expected_revision':1,'decision':'request_changes','reason':'Update'}).status_code==200

def test_csrf_and_revoked_edit_grant(client,db,tmp_path):
    from uuid import UUID
    from sqlalchemy import select
    from knowledge_ai.db import User
    p,v,c=drafts(client,db,tmp_path)
    url=f"/api/candidates/{c['id']}/review"
    csrf=client.headers.pop('x-csrf-token')
    assert client.post(url,json={'expected_revision':1,'decision':'approve'}).status_code==403
    client.headers['x-csrf-token']=csrf
    authenticate(client,'admin')
    with db.sessions() as s:uid=str(s.scalar(select(User).where(User.username=='contributor')).id)
    client.put(f'/api/profiles/{p}/grants/{uid}',json={'contribute':True})
    authenticate(client,'contributor')
    assert client.patch(f"/api/candidates/{c['id']}",json={'expected_revision':1,'payload':dict(c['payload'],name='Edited')}).status_code==200
    authenticate(client,'admin');client.put(f'/api/profiles/{p}/grants/{uid}',json={'contribute':False})
    authenticate(client,'contributor')
    assert client.patch(f"/api/candidates/{c['id']}",json={'expected_revision':2,'payload':c['payload']}).status_code==403

def test_preloaded_actor_cannot_bypass_live_disabled_user(client,db,tmp_path):
    from uuid import UUID
    from sqlalchemy import select
    from knowledge_ai.db import User
    from knowledge_ai.governance.policy import Actor
    from knowledge_ai.review.service import review_candidate
    from fastapi import HTTPException
    p,v,c=drafts(client,db,tmp_path)
    with db.sessions() as s:
        u=s.scalar(select(User).where(User.username=='owner-a'))
        actor=Actor(u.id,'owner',frozenset({UUID(p)}))
        with db.sessions() as other:
            other.get(User,u.id).active=False;other.commit()
        with pytest.raises(HTTPException) as error:review_candidate(s,actor,UUID(c['id']),1,'approve')
        assert error.value.status_code==403
