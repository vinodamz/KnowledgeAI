from dataclasses import replace
from uuid import UUID
import pytest
from fastapi import HTTPException
from knowledge_ai.governance.policy import Actor
from knowledge_ai.retrieval.planner import resolve_context, live_actor
from knowledge_ai.retrieval.service import RetrievalService
from knowledge_ai.profiles.models import Profile, KnowledgeVersion, ProfileGrant, ProjectDependency
from knowledge_ai.publication.builder import active
from knowledge_ai.publication.worker import run_one
from tests.integration.test_publication_generation import setup_publication, enqueue
from tests.integration.test_cited_answers import Embed, AnswerProvider
from tests.security.test_profile_owners import authenticate

@pytest.fixture
def published(client, db, tmp_path):
    ids,p,v,es,r,adapter = setup_publication(client,db,tmp_path)
    enqueue(client,p,v,es+[r]); assert run_one(db,client.app.state.settings,adapter)
    return ids,p,v,es,r,adapter

def deny_files(monkeypatch):
    import knowledge_ai.publication.reader as reader
    def fail(*a, **kw): raise AssertionError('Unauthorized store access')
    monkeypatch.setattr(reader, 'files_digest', fail)

@pytest.mark.parametrize('name', ['owner-b','reader'])
def test_forbidden_profile_and_draft_before_any_files(client,db,published,monkeypatch,name):
    ids,p,v,*_=published
    deny_files(monkeypatch)
    authenticate(client,name)
    assert client.post('/api/ask',json={'profile_id':p,'version_id':v,'query':'limits'}).status_code==403
    assert client.get('/api/graph',params={'version_ids':v}).status_code==403
    assert client.get('/api/available-contexts').json()==[]

@pytest.mark.parametrize('key,value', [('role','admin'),('generation_id','00000000-0000-0000-0000-000000000001'),('allowed_version_ids',[]),('grants',[])])
def test_forged_scope_inputs_rejected(client,db,published,key,value,monkeypatch):
    _,p,v,*_=published
    deny_files(monkeypatch)
    assert client.post('/api/ask',json={'profile_id':p,'version_id':v,'query':'limits',key:value}).status_code==422
    assert client.get('/api/graph',params={'version_ids':v,'generation_id':'forged'}).status_code==422

def test_cross_owner_read_grant_requires_released_or_archived(client,db,published):
    ids,p,v,*_=published
    with db.sessions() as s,s.begin():
        s.add(ProfileGrant(profile_id=UUID(p),user_id=UUID(ids['owner-b']),read=True))
    with db.sessions() as s:
        actor=Actor(UUID(ids['owner-b']),'owner')
        with pytest.raises(HTTPException) as err: resolve_context(s,actor,UUID(p),UUID(v))
        assert err.value.status_code==403
    for state in ('released','archived'):
        with db.sessions() as s,s.begin(): s.get(KnowledgeVersion,UUID(v)).status=state
        with db.sessions() as s:
            actor=Actor(UUID(ids['owner-b']),'owner');ctx=resolve_context(s,actor,UUID(p),UUID(v))
            answer=RetrievalService(s,actor,client.app.state.settings,embedding=Embed(),answer_provider=AnswerProvider()).answer(ctx,'limits')
            assert answer.status=='answered'
            assert {i['version_id'] for i in answer.context.items}=={v}

def test_exact_version_excludes_other_authoring_version(client,db,published):
    ids,p,v,*_=published
    with db.sessions() as s,s.begin():
        other=KnowledgeVersion(profile_id=UUID(p),label='other');s.add(other);s.flush();other_id=other.id
    with db.sessions() as s:
        actor=Actor(UUID(ids['owner-a']),'owner');ctx=resolve_context(s,actor,UUID(p),other_id)
        embed=Embed(); result=RetrievalService(s,actor,client.app.state.settings,embedding=embed,answer_provider=AnswerProvider()).answer(ctx,'limits')
        assert result.status=='insufficient_knowledge' and embed.calls==0

def test_revoked_dependency_denies_all_store_access(client,db,published,monkeypatch):
    ids,p,v,*_=published
    with db.sessions() as s,s.begin():
        s.get(KnowledgeVersion,UUID(v)).status='released'
        project=Profile(kind='project',name='Implementation',owner_id=UUID(ids['owner-b']));s.add(project);s.flush()
        version=KnowledgeVersion(profile_id=project.id,label='pin');s.add(version);s.flush()
        s.add(ProjectDependency(project_version_id=version.id,product_version_id=UUID(v)))
        grant=ProfileGrant(profile_id=UUID(p),user_id=UUID(ids['owner-b']),read=True);s.add(grant)
        project_id,version_id=project.id,version.id
    with db.sessions() as s:
        actor=live_actor(s,Actor(UUID(ids['owner-b']),'owner'));ctx=resolve_context(s,actor,project_id,version_id)
    with db.sessions() as s,s.begin(): s.delete(s.get(ProfileGrant,(UUID(p),UUID(ids['owner-b']))))
    deny_files(monkeypatch)
    with db.sessions() as s:
        with pytest.raises(HTTPException) as err: RetrievalService(s,actor,client.app.state.settings).answer(ctx,'limits')
        assert err.value.status_code==403

@pytest.mark.parametrize('failure',['failed','tampered','embedding','seal'])
def test_invalid_generation_fails_closed(client,db,published,failure):
    ids,p,v,es,r,adapter=published
    with db.sessions() as s:
        actor=Actor(UUID(ids['owner-a']),'owner');ctx=resolve_context(s,actor,UUID(p),UUID(v));g=active(s)
        if failure=='failed':
            # Immutable registry is independently tested by publication; simulate
            # an unavailable pinned registry row without altering database history.
            from unittest.mock import patch
            from knowledge_ai.publication.models import PublicationGeneration
            original=s.get
            def get(cls,key,*args,**kw): return None if cls is PublicationGeneration else original(cls,key,*args,**kw)
            with patch.object(s,'get',side_effect=get):
                with pytest.raises(HTTPException): RetrievalService(s,actor,client.app.state.settings).answer(ctx,'limits')
            return
        if failure=='tampered':
            file=next((adapter.root/str(g.id)).rglob('vdb_chunks.json'));file.write_text('{}')
        if failure=='embedding': client.app.state.settings.embedding_model='wrong-model'
        if failure=='seal': (adapter.root/str(g.id)/'verified.json').write_text('{}')
        with pytest.raises(HTTPException): RetrievalService(s,actor,client.app.state.settings).answer(ctx,'limits')

def test_inflight_pin_survives_central_generation_change(client,db,published):
    ids,p,v,es,r,adapter=published
    with db.sessions() as s:
        actor=Actor(UUID(ids['owner-a']),'owner');ctx=resolve_context(s,actor,UUID(p),UUID(v))
    enqueue(client,p,v,[es[0]],key='next-generation');assert run_one(db,client.app.state.settings,adapter)
    with db.sessions() as s:
        assert active(s).id != ctx.generation_id
        result=RetrievalService(s,actor,client.app.state.settings,embedding=Embed(),answer_provider=AnswerProvider()).answer(ctx,'limits')
        assert result.context.policy_context['generation_id']==str(ctx.generation_id)
        assert len(result.citations)==3

def test_central_graph_rejects_unauthorized_selection_before_authorized_store(client,db,published,monkeypatch):
    ids,p,v,*_=published
    with db.sessions() as s,s.begin():
        other=Profile(kind='product',name='Private',owner_id=UUID(ids['owner-b']));s.add(other);s.flush()
        version=KnowledgeVersion(profile_id=other.id,label='private');s.add(version);s.flush();other_id=version.id
    deny_files(monkeypatch)
    result=client.get('/api/graph',params=[('version_ids',v),('version_ids',str(other_id))])
    assert result.status_code==403
