import hashlib
from uuid import UUID
import numpy as np
import pytest
from sqlalchemy import select, text
from tests.integration.test_review_lifecycle import relation_drafts, decide
from knowledge_ai.publication.worker import run_one, WRITER_LOCK
from knowledge_ai.publication.models import PublicationGeneration, PublicationJob, ActivePublication
from knowledge_ai.publication.builder import active
from knowledge_ai.adapters.lightrag import LightRAGAdapter, files_digest

async def deterministic_embeddings(texts):
    return np.asarray([[b / 255 + 0.01 for b in hashlib.sha256(t.encode()).digest()] for t in texts], dtype=np.float32)

def setup_publication(client, db, tmp_path):
    ids,p,v,es,r = relation_drafts(client, db, tmp_path)
    for c in es+[r]: assert decide(client,c).status_code == 200
    settings = client.app.state.settings
    settings.publication_directory = str(tmp_path/'publication')
    settings.embedding_dimensions = 32
    adapter = LightRAGAdapter(settings, embedding=deterministic_embeddings)
    return ids,p,v,es,r,adapter

def enqueue(client,p,v,cs,key='one'):
    response=client.post('/api/publications',json={'profile_id':p,'version_id':v,'candidates':[{'candidate_id':c['id'],'revision':c['revision']} for c in cs],'idempotency_key':key})
    assert response.status_code == 202,response.text
    return response.json()

def test_actual_sdk_verified_publication(client,db,tmp_path):
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    job=enqueue(client,p,v,es+[r])
    assert run_one(db,client.app.state.settings,adapter)
    result=client.get('/api/publications/'+job['id']).json()
    assert result['status']=='published', result
    with db.sessions() as s:
        g=active(s)
        assert len(g.scope_manifest['facts'])==3
        assert g.verification['partitions'][v]['counts']=={'nodes':4,'edges':3,'entity_vectors':4,'relation_vectors':3,'chunks':3,'chunk_vectors':3}
        adapter.verify_seal(g.id,g.verification)
    assert all(c['status']=='published' for c in client.get(f'/api/versions/{v}/candidates').json())

STORE_BOUNDARIES = [f'{when}_{store}_{method}' for store, methods in (
    ('chunks', ('upsert','index_done_callback')), ('chunk_vectors', ('upsert','index_done_callback')),
    ('nodes', ('upsert_nodes_batch',)), ('edges', ('upsert_edges_batch','index_done_callback')),
    ('entity_vectors', ('upsert','index_done_callback')), ('relation_vectors', ('upsert','index_done_callback')),
) for method in methods for when in ('before','after')]
OTHER_BOUNDARIES=['before_insert','after_insert','verified_graph','verified_chunks','verified_vectors','after_verify','before_seal','after_seal']
WORKER_BOUNDARIES=['after_staging_commit','after_build','after_verification_commit','before_activation','before_activation_commit']

@pytest.mark.parametrize('boundary',STORE_BOUNDARIES+OTHER_BOUNDARIES+WORKER_BOUNDARIES)
def test_partial_index_failure_never_activates(client,db,tmp_path,boundary):
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    first=enqueue(client,p,v,[es[0]])
    run_one(db,client.app.state.settings,adapter)
    with db.sessions() as s:
        original=active(s); assert original is not None
        original_id=original.id
        original_digest=files_digest(adapter.root/str(original_id))
    job=enqueue(client,p,v,es+[r],key='two')
    hit=[]
    def fail(at):
        if at==boundary and not hit:
            hit.append(at);raise RuntimeError('Injected interruption')
    adapter.fault=fail
    run_one(db,client.app.state.settings,adapter,fault=fail)
    assert hit, boundary
    result=client.get('/api/publications/'+job['id']).json()
    assert result['status']=='publication_failed'
    with db.sessions() as s: assert active(s).id==original_id
    assert files_digest(adapter.root/str(original_id))==original_digest
    assert client.get(f'/api/versions/{v}/publication').json()['generation_id']==str(original_id)


def test_retry_crash_idempotency_and_single_writer(client,db,tmp_path):
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    job=enqueue(client,p,v,es+[r]);assert enqueue(client,p,v,es+[r])['id']==job['id']
    class Crash(BaseException):pass
    def crash(at):
        if at=='after_staging_commit':raise Crash()
    with pytest.raises(Crash):run_one(db,client.app.state.settings,adapter,fault=crash)
    partial=client.get('/api/publications/'+job['id']).json()['generation_id']
    with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        lock.execute(text('SELECT pg_advisory_lock(:k)'),{'k':WRITER_LOCK})
        assert not run_one(db,client.app.state.settings,adapter)
        lock.execute(text('SELECT pg_advisory_unlock(:k)'),{'k':WRITER_LOCK})
    run_one(db,client.app.state.settings,adapter)
    result=client.get('/api/publications/'+job['id']).json()
    assert result['status']=='published' and result['generation_id']!=partial and result['attempts']==2
    assert not run_one(db,client.app.state.settings,adapter)

@pytest.mark.parametrize('change',['edit','owner','reject','cas'])
def test_changes_during_build_prevent_activation(client,db,tmp_path,change):
    ids,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    job=enqueue(client,p,v,es+[r])
    def mutate(at):
        if at!='before_activation':return
        if change=='edit':
            assert client.patch(f"/api/candidates/{es[0]['id']}",json={'expected_revision':1,'payload':dict(es[0]['payload'],name='Changed')}).status_code==200
        elif change=='reject':assert decide(client,es[0],'reject','Withdraw approval').status_code==200
        elif change=='owner':
            from tests.security.test_profile_owners import authenticate
            authenticate(client,'admin')
            assert client.put(f'/api/profiles/{p}/owner',json={'owner_id':ids['owner-b']}).status_code==200
        else:
            with db.sessions() as s,s.begin():
                replacement=PublicationGeneration(scope_manifest={'facts':[]},status='active',verification={})
                s.add(replacement);s.flush();s.get(ActivePublication,1).generation_id=replacement.id
    run_one(db,client.app.state.settings,adapter,fault=mutate)
    assert client.get('/api/publications/'+job['id']).json()['status']=='publication_failed'
    with db.sessions() as s:
        g=active(s)
        assert g is None if change!='cas' else g.scope_manifest=={'facts':[]}


def test_unavailable_embedding_retry_and_after_commit(client,db,tmp_path):
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    job=enqueue(client,p,v,es+[r])
    async def unavailable(texts):raise ConnectionError('offline')
    adapter.embedding=unavailable
    run_one(db,client.app.state.settings,adapter)
    failed=client.get('/api/publications/'+job['id']).json()
    assert failed['status']=='publication_failed'
    assert client.post('/api/publications/'+job['id']+'/retry').status_code==202
    adapter.embedding=deterministic_embeddings
    def after_commit(at):
        if at=='after_activation_commit':raise RuntimeError('process lost response')
    run_one(db,client.app.state.settings,adapter,fault=after_commit)
    assert client.get('/api/publications/'+job['id']).json()['status']=='published'


def test_draft_edits_and_ingestion_leave_actual_active_stores_unchanged(client,db,tmp_path):
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    enqueue(client,p,v,es+[r]);run_one(db,client.app.state.settings,adapter)
    with db.sessions() as s:g=active(s);gid=g.id
    before=files_digest(adapter.root/str(gid))
    edited=client.patch(f"/api/candidates/{es[0]['id']}",json={'expected_revision':1,'payload':dict(es[0]['payload'],name='Next draft')})
    assert edited.status_code==200
    from knowledge_ai.ingestion.jobs import run_one as extract
    from tests.integration.test_draft_ingestion import FakeProvider
    response=client.post(f'/api/versions/{v}/sources',files={'file':('new.txt',b'Controller C unapproved secret unrelated fact','text/plain')})
    assert response.status_code==201,response.text
    extract(db,client.app.state.settings,FakeProvider())
    assert files_digest(adapter.root/str(gid))==before
    # Publishing another exact existing entity preserves the old approved relation/endpoint.
    enqueue(client,p,v,[es[1]],key='preserve');run_one(db,client.app.state.settings,adapter)
    with db.sessions() as s:
        facts=active(s).scope_manifest['facts']
        assert len(facts)==3 and any(f['candidate_id']==es[0]['id'] and f['revision']==1 for f in facts)


def test_scoped_selection_preserves_other_owners_and_does_not_sweep(client,db,tmp_path):
    from tests.security.test_profile_owners import authenticate
    from tests.integration.test_draft_ingestion import upload
    from knowledge_ai.ingestion.jobs import run_one as extract
    ids,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    enqueue(client,p,v,[es[0]]);run_one(db,client.app.state.settings,adapter)
    authenticate(client,'admin')
    p2=client.post('/api/profiles',json={'kind':'product','name':'Separate owner','owner_id':ids['owner-b']}).json()['id']
    authenticate(client,'owner-b')
    v2=client.post(f'/api/profiles/{p2}/versions',json={'label':'1'}).json()['id']
    m=client.post(f'/api/profiles/{p2}/models',json={}).json()['id']
    e=client.post(f'/api/models/{m}/entities',json={'name':'Controller','attributes':[]}).json()['entities'][0]['id']
    client.put(f'/api/models/{m}/entities/{e}/qualification',json={'qualification':'Independent'})
    client.post(f'/api/models/{m}/publish');client.put(f'/api/versions/{v2}/model',json={'model_revision_id':m})
    upload(client,v2)
    class Provider:
        def extract(self,chunks,model):
            return {'entities':[{'key':'same','type_id':e,'type_name':'Controller','name':'a','attributes':{},'evidence':[{'chunk_id':chunks[0]['chunk_id'],'start':0,'end':10,'excerpt':'Controller'}]}],'relations':[]}
    extract(db,client.app.state.settings,Provider())
    c=client.get(f'/api/versions/{v2}/candidates').json()[0];assert decide(client,c).status_code==200
    enqueue(client,p2,v2,[c],key='second-owner');run_one(db,client.app.state.settings,adapter)
    with db.sessions() as s:
        g=active(s);assert len(g.scope_manifest['facts'])==2
        assert {f['candidate_id'] for f in g.scope_manifest['facts']}=={es[0]['id'],c['id']}
        assert set(g.verification['partitions'])=={v,v2}
        assert g.verification['partitions'][v]['workspace']!=g.verification['partitions'][v2]['workspace']
    forbidden=client.post('/api/publications',json={'profile_id':p,'version_id':v,'candidates':[{'candidate_id':es[1]['id'],'revision':1}],'idempotency_key':'steal'})
    assert forbidden.status_code==403
    authenticate(client,'owner-a')
    enqueue(client,p,v,[es[1]],key='add-one');run_one(db,client.app.state.settings,adapter)
    with db.sessions() as s:assert {f['candidate_id'] for f in active(s).scope_manifest['facts']}=={es[0]['id'],es[1]['id'],c['id']}


def test_relation_reification_preserves_selfloops_parallel_direction(client,db,tmp_path):
    from knowledge_ai.review.models import Candidate
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    with db.sessions() as s,s.begin():
        original=s.get(Candidate,(UUID(r['id']),1))
        reverse=Candidate(source_revision_id=original.source_revision_id,kind='relation',payload=dict(original.payload,source_candidate_id=original.payload['target_candidate_id'],target_candidate_id=original.payload['source_candidate_id']),evidence=original.evidence,state='pending')
        loop=Candidate(source_revision_id=original.source_revision_id,kind='relation',payload=dict(original.payload,target_candidate_id=original.payload['source_candidate_id']),evidence=original.evidence,state='pending')
        parallel=Candidate(source_revision_id=original.source_revision_id,kind='relation',payload=dict(original.payload,description='Separately approved assertion'),evidence=original.evidence,state='pending')
        s.add_all([reverse,loop,parallel]);s.flush()
        more=[{'id':str(c.id),'revision':1} for c in (reverse,loop,parallel)]
    for c in more:assert decide(client,c).status_code==200
    job=enqueue(client,p,v,es+[r]+more);run_one(db,client.app.state.settings,adapter)
    assert client.get('/api/publications/'+job['id']).json()['status']=='published'
    with db.sessions() as s:
        g=active(s)
        assert g.verification['partitions'][v]['counts']['nodes']==10
        assert g.verification['partitions'][v]['counts']['edges']==12
        assert len([f for f in g.scope_manifest['facts'] if f['kind']=='relation'])==4


def test_scoped_reader_refuses_staging_and_tampered_partition(client,db,tmp_path):
    from knowledge_ai.publication.reader import verified_partition
    from knowledge_ai.governance.policy import Actor
    from fastapi import HTTPException
    ids,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    enqueue(client,p,v,es+[r]);run_one(db,client.app.state.settings,adapter)
    owner=Actor(UUID(ids['owner-a']),'owner',frozenset({UUID(p)}))
    outsider=Actor(UUID(ids['owner-b']),'owner')
    with db.sessions() as s:
        g=active(s);path=adapter.root/str(g.id);before=files_digest(path)
        with pytest.raises(HTTPException) as denied:verified_partition(s,outsider,client.app.state.settings,g.id,UUID(v))
        assert denied.value.status_code==403
        result=verified_partition(s,owner,client.app.state.settings,g.id,UUID(v))
        assert len(result.facts)==3 and files_digest(path)==before
        (path/result.workspace/'tampered.json').write_text('{}')
        with pytest.raises(HTTPException) as corrupt:verified_partition(s,owner,client.app.state.settings,g.id,UUID(v))
        assert corrupt.value.status_code==503
        staging=PublicationGeneration(scope_manifest={'facts':[]},status='staging');s.add(staging);s.flush()
        with pytest.raises(HTTPException):verified_partition(s,owner,client.app.state.settings,staging.id,UUID(v))


def test_real_ollama_publication(client,db,tmp_path):
    import os
    if os.environ.get('KNOWLEDGE_AI_LIVE_OLLAMA')!='1':pytest.skip('Opt-in local Ollama integration proof')
    _,p,v,es,r,_=setup_publication(client,db,tmp_path)
    settings=client.app.state.settings
    settings.embedding_dimensions=768;settings.embedding_base_url='http://127.0.0.1:11434'
    adapter=LightRAGAdapter(settings)
    job=enqueue(client,p,v,es+[r]);run_one(db,settings,adapter)
    assert client.get('/api/publications/'+job['id']).json()['status']=='published'
    with db.sessions() as s:
        generation=active(s);adapter.verify_seal(generation.id,generation.verification)
        assert generation.verification['partitions'][v]['counts']['chunk_vectors']==3


def test_reader_draft_boundary_and_redacted_job_status(client,db,tmp_path):
    from tests.security.test_profile_owners import authenticate
    from knowledge_ai.profiles.models import KnowledgeVersion
    ids,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    job=enqueue(client,p,v,es+[r]);run_one(db,client.app.state.settings,adapter)
    authenticate(client,'admin')
    assert client.put(f'/api/profiles/{p}/grants/{ids["reader"]}',json={'read':True,'contribute':False}).status_code==200
    authenticate(client,'reader')
    assert client.get('/api/publications/'+job['id']).status_code==403
    assert client.get('/api/publications',params={'version_id':v}).status_code==403
    assert client.get(f'/api/versions/{v}/publication').status_code==403
    # Task9 owns the release operation. Simulate its resulting lifecycle state here.
    with db.sessions() as s,s.begin():s.get(KnowledgeVersion,UUID(v)).status='released'
    result=client.get('/api/publications/'+job['id'])
    assert result.status_code==200 and 'selection' not in result.json() and 'error' not in result.json()
    assert client.get('/api/publications',params={'version_id':v}).json()[0]['status']=='published'
    assert len(client.get(f'/api/versions/{v}/publication').json()['facts'])==3


def test_reader_authorizes_before_files_and_preserves_pinned_retired_generation(client,db,tmp_path,monkeypatch):
    from knowledge_ai.publication import reader
    from knowledge_ai.governance.policy import Actor
    from fastapi import HTTPException
    ids,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    enqueue(client,p,v,[es[0]]);run_one(db,client.app.state.settings,adapter)
    owner=Actor(UUID(ids['owner-a']),'owner',frozenset({UUID(p)}))
    outsider=Actor(UUID(ids['owner-b']),'owner')
    with db.sessions() as s:
        pinned=reader.pin_generation(s)
    enqueue(client,p,v,es+[r],key='next');run_one(db,client.app.state.settings,adapter)
    before=files_digest(adapter.root)
    original_digest=reader.files_digest
    reads=[]
    def record_read(path):
        reads.append(path)
        return original_digest(path)
    monkeypatch.setattr(reader,'files_digest',record_read)
    with db.sessions() as s:
        assert reader.pin_generation(s)!=pinned
        with pytest.raises(HTTPException) as denied:
            reader.verified_partition(s,outsider,client.app.state.settings,pinned,UUID(v))
        assert denied.value.status_code==403 and reads==[]
        old=reader.verified_partition(s,owner,client.app.state.settings,pinned,UUID(v))
        assert len(old.facts)==1 and len(reads)==1
        assert s.get(PublicationGeneration,pinned).status=='retired'
    assert files_digest(adapter.root)==before

@pytest.mark.parametrize('filename',['graph_chunk_entity_relation.graphml','vdb_entities.json','kv_store_text_chunks.json'])
def test_persisted_payload_tampering_rejected_before_activation(client,db,tmp_path,filename):
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    job=enqueue(client,p,v,es+[r])
    def corrupt(at):
        if at=='before_activation':
            path=next(adapter.root.rglob(filename));path.write_text('corrupt')
    run_one(db,client.app.state.settings,adapter,fault=corrupt)
    assert client.get('/api/publications/'+job['id']).json()['status']=='publication_failed'
    with db.sessions() as s:assert active(s) is None


@pytest.mark.parametrize('field',['content','file_path','source_id'])
def test_persisted_chunk_payload_corruption_before_verification_never_activates(client,db,tmp_path,field):
    import json
    _,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    job=enqueue(client,p,v,es+[r])
    def corrupt(at):
        if at=='after_insert':
            path=next(adapter.root.rglob('kv_store_text_chunks.json'))
            payload=json.loads(path.read_text())
            next(iter(payload.values()))[field]='unapproved replacement'
            path.write_text(json.dumps(payload))
    adapter.fault=corrupt
    run_one(db,client.app.state.settings,adapter)
    assert client.get('/api/publications/'+job['id']).json()['status']=='publication_failed'
    with db.sessions() as s:assert active(s) is None


def test_embedding_identity_is_sealed_and_reader_rejects_incompatible_configuration(client,db,tmp_path,monkeypatch):
    from knowledge_ai.publication import reader
    from knowledge_ai.governance.policy import Actor
    from fastapi import HTTPException
    ids,p,v,es,r,adapter=setup_publication(client,db,tmp_path)
    enqueue(client,p,v,es+[r]);run_one(db,client.app.state.settings,adapter)
    settings=client.app.state.settings
    owner=Actor(UUID(ids['owner-a']),'owner',frozenset({UUID(p)}))
    with db.sessions() as s:
        g=active(s)
        assert g.verification['embedding']=={'provider':'ollama','model':settings.embedding_model,'dimensions':32}
        adapter.verify_seal(g.id,g.verification)
        def unexpected_read(path):raise AssertionError('Incompatible embedding must fail before files are read')
        monkeypatch.setattr(reader,'files_digest',unexpected_read)
        settings.embedding_model='different-model-same-dimensions'
        with pytest.raises(HTTPException) as denied:reader.verified_partition(s,owner,settings,g.id,UUID(v))
        assert denied.value.status_code==503
        settings.embedding_model=g.verification['embedding']['model'];settings.embedding_dimensions=768
        with pytest.raises(HTTPException) as denied:reader.verified_partition(s,owner,settings,g.id,UUID(v))
        assert denied.value.status_code==503
        settings.embedding_dimensions=32
        # Simulate an incompatible report only in memory; persisted reports are immutable.
        g.verification={**g.verification,'embedding':{**g.verification['embedding'],'provider':'another-provider'}}
        with s.no_autoflush, pytest.raises(HTTPException) as denied:reader.verified_partition(s,owner,settings,g.id,UUID(v))
        assert denied.value.status_code==503


@pytest.mark.parametrize('model',['','   ',' model','model '])
def test_embedding_identity_requires_a_valid_model(model):
    from types import SimpleNamespace
    from knowledge_ai.adapters.lightrag import embedding_identity
    with pytest.raises(ValueError):embedding_identity(SimpleNamespace(embedding_model=model,embedding_dimensions=32))
