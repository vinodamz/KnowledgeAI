from tests.integration.test_draft_ingestion import scope,upload,FakeProvider
from knowledge_ai.ingestion.jobs import run_one

def drafts(client,db,tmp_path):
    p,v,m=scope(client,db);client.app.state.settings.object_directory=str(tmp_path)
    upload(client,v);run_one(db,client.app.state.settings,FakeProvider())
    return p,v,client.get(f'/api/versions/{v}/candidates').json()[0]

def test_stale_revision_cannot_be_approved(client,db,tmp_path):
    _,v,c=drafts(client,db,tmp_path)
    r=client.patch(f"/api/candidates/{c['id']}",json={'expected_revision':1,'payload':dict(c['payload'],name='Corrected')})
    assert r.status_code==200,r.text
    assert r.json()['revision']==2
    assert client.post(f"/api/candidates/{c['id']}/review",json={'expected_revision':1,'decision':'approve'}).status_code==409

def test_decision_history_and_reason(client,db,tmp_path):
    _,v,c=drafts(client,db,tmp_path)
    url=f"/api/candidates/{c['id']}/review"
    assert client.post(url,json={'expected_revision':1,'decision':'reject'}).status_code==422
    r=client.post(url,json={'expected_revision':1,'decision':'request_changes','reason':'Evidence insufficient'})
    assert r.status_code==200,r.text
    assert r.json()['previous_state']=='pending'
    assert len(r.json()['checksum'])==64
    assert client.get(f'/api/versions/{v}/candidates').json()[0]['status']=='changes_requested'

from uuid import UUID
from sqlalchemy import select
from knowledge_ai.review.models import Candidate,ReviewDecision
from knowledge_ai.review.service import publication_readiness
from tests.security.test_profile_owners import setup,authenticate

def relation_drafts(client,db,tmp_path):
    ids=setup(client,db)
    p=client.post('/api/profiles',json={'kind':'product','name':'Relations','owner_id':ids['owner-a']}).json()['id']
    authenticate(client,'owner-a')
    v=client.post(f'/api/profiles/{p}/versions',json={'label':'1'}).json()['id']
    m=client.post(f'/api/profiles/{p}/models',json={}).json()['id']
    e=client.post(f'/api/models/{m}/entities',json={'name':'Controller','attributes':[]}).json()['entities'][0]['id']
    client.put(f'/api/models/{m}/entities/{e}/qualification',json={'qualification':'Independent'})
    r=client.post(f'/api/models/{m}/relations',json={'name':'connects','source_type_id':e,'target_type_id':e}).json()['relations'][0]['id']
    assert client.post(f'/api/models/{m}/publish').status_code==200
    client.put(f'/api/versions/{v}/model',json={'model_revision_id':m})
    client.app.state.settings.object_directory=str(tmp_path)
    upload(client,v)
    class Provider:
        def extract(self,chunks,model):
            ev=[{'chunk_id':chunks[0]['chunk_id'],'start':0,'end':10,'excerpt':'Controller'}]
            return {'entities':[{'key':k,'type_id':e,'type_name':'Controller','name':k,'attributes':{},'evidence':ev} for k in ('a','b')],'relations':[{'type_id':r,'type_name':'connects','source':'a','target':'b','evidence':ev}]}
    run_one(db,client.app.state.settings,Provider())
    rows=client.get(f'/api/versions/{v}/candidates').json()
    return ids,p,v,[x for x in rows if x['kind']=='entity'],next(x for x in rows if x['kind']=='relation')

def decide(client,c,decision='approve',reason=None):
    return client.post(f"/api/candidates/{c['id']}/review",json={'expected_revision':c['revision'],'decision':decision,'reason':reason})

def test_relation_approval_does_not_approve_endpoints_and_manifest_closure(client,db,tmp_path):
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    assert decide(client,r).status_code==200
    with db.sessions() as s:
        assert [s.get(Candidate,(UUID(e['id']),1)).state for e in es]==['pending','pending']
        relation=s.get(Candidate,(UUID(r['id']),1))
        assert not publication_readiness(s,relation)['ready']
    for e in es:assert decide(client,e).status_code==200
    with db.sessions() as s:
        relation=s.get(Candidate,(UUID(r['id']),1))
        assert not publication_readiness(s,relation)['ready']
        manifest={(UUID(e['id']),1) for e in es}
        assert publication_readiness(s,relation,target_manifest=manifest)['ready']
    new=client.patch(f"/api/candidates/{es[0]['id']}",json={'expected_revision':1,'payload':dict(es[0]['payload'],name='Changed')})
    assert new.status_code==200
    assert decide(client,r).status_code==409
    with db.sessions() as s:
        assert not publication_readiness(s,s.get(Candidate,(UUID(r['id']),1)),target_manifest=manifest)['ready']
    revised=client.patch(f"/api/candidates/{r['id']}",json={'expected_revision':1,'payload':dict(r['payload'],source_candidate_revision=2)})
    assert revised.status_code==200
    assert revised.json()['state']=='pending'

def test_batch_stale_is_atomic_and_reject_requires_reason(client,db,tmp_path):
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    assert client.patch(f"/api/candidates/{es[1]['id']}",json={'expected_revision':1,'payload':dict(es[1]['payload'],name='New')}).status_code==200
    result=client.post('/api/review/batch',json={'candidates':[{'candidate_id':e['id'],'revision':1} for e in es],'decision':'approve'})
    assert result.status_code==409
    with db.sessions() as s:
        assert s.get(Candidate,(UUID(es[0]['id']),1)).state=='pending'
        assert list(s.scalars(select(ReviewDecision)))==[]
    assert decide(client,es[0],'reject','Incorrect').status_code==200
    assert next(x for x in client.get(f'/api/versions/{v}/candidates').json() if x['id']==es[0]['id'])['reason']=='Incorrect'

def test_evidence_edit_checksum_and_immutable_history(client,db,tmp_path):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    e=es[0];assert decide(client,e).status_code==200
    old_checksum=client.get(f'/api/versions/{v}/candidates').json()[0]['checksum']
    bad=[dict(e['evidence'][0],excerpt='fabricated')]
    assert client.patch(f"/api/candidates/{e['id']}",json={'expected_revision':1,'payload':e['payload'],'evidence':bad}).status_code==422
    good=[dict(e['evidence'][0],end=9,page_end=9,excerpt='Controlle')]
    edited=client.patch(f"/api/candidates/{e['id']}",json={'expected_revision':1,'payload':e['payload'],'evidence':good})
    assert edited.status_code==200,edited.text
    assert edited.json()['checksum']!=old_checksum and edited.json()['state']=='pending'
    with db.sessions() as s:
        assert s.get(Candidate,(UUID(e['id']),1)).state=='approved'
        with pytest.raises(DBAPIError):s.execute(text("UPDATE review_decisions SET reason='tampered'"));s.commit()
        s.rollback()

def test_model_suggestion_never_instance_ready(client,db,tmp_path):
    _,v,c=drafts(client,db,tmp_path)
    assert decide(client,c).status_code==200
    row=client.get(f'/api/versions/{v}/candidates').json()[0]
    assert row['status']=='approved_but_blocked'
    assert 'Model suggestion cannot publish as an instance' in row['blockers']

def test_cross_version_endpoint_refused(client,db,tmp_path):
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    other=client.post(f'/api/profiles/{p}/versions',json={'label':'2'}).json()['id']
    from knowledge_ai.ingestion.sources import SourceRevision
    from knowledge_ai.profiles.models import KnowledgeVersion
    with db.sessions() as s:
        original=s.get(Candidate,(UUID(es[0]['id']),1));source=s.get(SourceRevision,original.source_revision_id)
        s.get(KnowledgeVersion,UUID(other)).model_revision_id=source.model_revision_id
        source2=SourceRevision(profile_id=source.profile_id,knowledge_version_id=UUID(other),model_revision_id=source.model_revision_id,content_hash='different',object_key='different',provenance={},access_policy={},uploaded_by=source.uploaded_by,chunks=source.chunks)
        s.add(source2);s.flush()
        e=Candidate(source_revision_id=source2.revision_id,kind='entity',payload=original.payload,evidence=original.evidence,state='pending');s.add(e);s.flush();eid=str(e.id);s.commit()
    result=client.patch(f"/api/candidates/{r['id']}",json={'expected_revision':1,'payload':dict(r['payload'],source_candidate_id=eid)})
    assert result.status_code==422 and 'pinned instance link' in result.text

def test_edited_payload_must_match_exact_model_and_canonical(client,db,tmp_path):
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    e=es[0];url=f"/api/candidates/{e['id']}"
    for payload in [dict(e['payload'],type_id=None),dict(e['payload'],attributes={'invented':'x'}),dict(e['payload'],canonical_concept_id='invented'),dict(e['payload'],name=7)]:
        assert client.patch(url,json={'expected_revision':1,'payload':payload}).status_code==422

def test_batch_exact_success_and_previous_state(client,db,tmp_path):
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    selected=es+[r]
    response=client.post('/api/review/batch',json={'candidates':[{'candidate_id':c['id'],'revision':1} for c in selected],'decision':'approve'})
    assert response.status_code==200,response.text
    assert len(response.json())==3
    assert decide(client,es[0],'reject','Withdraw').json()['previous_state']=='approved'
    with db.sessions() as s:
        relation=s.get(Candidate,(UUID(r['id']),1))
        assert not publication_readiness(s,relation,target_manifest={(UUID(e['id']),1) for e in es})['ready']

def test_invalid_batch_rolls_back_prior_member(client,db,tmp_path):
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    assert client.patch(f"/api/candidates/{es[0]['id']}",json={'expected_revision':1,'payload':dict(es[0]['payload'],name='Changed')}).status_code==200
    response=client.post('/api/review/batch',json={'candidates':[{'candidate_id':es[1]['id'],'revision':1},{'candidate_id':r['id'],'revision':1}],'decision':'approve'})
    assert response.status_code==409
    with db.sessions() as s:
        assert s.get(Candidate,(UUID(es[1]['id']),1)).state=='pending'
        assert list(s.scalars(select(ReviewDecision)))==[]

def test_rebound_scope_blocks_readiness(client,db,tmp_path):
    _,p,v,es,r=relation_drafts(client,db,tmp_path)
    assert decide(client,es[0]).status_code==200
    from knowledge_ai.profiles.models import KnowledgeVersion
    with db.sessions() as s:
        s.get(KnowledgeVersion,UUID(v)).status='archived';s.commit()
        result=publication_readiness(s,s.get(Candidate,(UUID(es[0]['id']),1)))
        assert not result['ready'] and any('scope' in b for b in result['blockers'])
