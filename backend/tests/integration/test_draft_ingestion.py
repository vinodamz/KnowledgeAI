from tests.security.test_profile_owners import setup, authenticate

def scope(client, db):
    ids=setup(client,db)
    p=client.post('/api/profiles',json={'kind':'product','name':'Manual','owner_id':ids['owner-a']}).json()['id']
    authenticate(client,'owner-a')
    v=client.post(f'/api/profiles/{p}/versions',json={'label':'1'}).json()['id']
    m=client.post(f'/api/profiles/{p}/models',json={}).json()['id']
    client.post(f'/api/models/{m}/publish')
    client.put(f'/api/versions/{v}/model',json={'model_revision_id':m})
    return p,v,m

def test_upload_creates_isolated_drafts(client,db,tmp_path):
    p,v,m=scope(client,db)
    client.app.state.settings.object_directory=str(tmp_path)
    r=client.post(f'/api/versions/{v}/sources',files={'file':('manual.txt',b'Controller operates equipment.','text/plain')})
    assert r.status_code==201,r.text

class FakeProvider:
    def extract(self,chunks,model):
        c=chunks[0]
        type_id=model['entities'][0]['id'] if model['entities'] else None
        return {'entities':[{'key':'a','type_id':type_id,'type_name':'Controller','name':'Controller','attributes':{},'evidence':[{'chunk_id':c['chunk_id'],'start':0,'end':10,'excerpt':c['text'][:10]}]}], 'relations':[]}

def upload(client,v,content=b'Controller operates equipment.',name='manual.txt'):
    return client.post(f'/api/versions/{v}/sources',files={'file':(name,content,'text/plain')})

def test_worker_evidence_unknown_definition_idempotence_and_isolation(client,db,tmp_path,monkeypatch):
    from sqlalchemy import event,select
    from knowledge_ai.ingestion.jobs import run_one,ExtractionJob
    from knowledge_ai.ingestion.sources import SourceRevision
    from knowledge_ai.review.models import Candidate,RawExtraction
    p,v,m=scope(client,db)
    client.app.state.settings.object_directory=str(tmp_path)
    writes=[]
    def capture(conn,cursor,statement,parameters,context,many):
        if statement.lstrip().lower().startswith(('insert','update','delete')): writes.append(statement.lower())
    event.listen(db.engine,'before_cursor_execute',capture)
    r=upload(client,v).json(); duplicate=upload(client,v).json()
    assert duplicate['duplicate'] and duplicate['job_id']==r['job_id']
    assert run_one(db,client.app.state.settings,FakeProvider())
    assert client.get('/api/jobs/'+r['job_id']).json()['status']=='succeeded'
    rows=client.get(f'/api/versions/{v}/candidates').json()
    assert len(rows)==1 and rows[0]['kind']=='model_suggestion' and rows[0]['state']=='pending'
    ev=rows[0]['evidence'][0]
    assert ev['page']==1 and ev['excerpt']=='Controller' and ev['start']==0 and ev['end']==10
    assert not any(any(store in s for store in ('published_chunks','published_entities','published_relations','publication_generations')) for s in writes)
    with db.sessions() as s:
        assert len(list(s.scalars(select(ExtractionJob))))==1
        assert len(list(s.scalars(select(RawExtraction))))==1
    assert len(list(tmp_path.iterdir()))==1
    assert not run_one(db,client.app.state.settings,FakeProvider())


def test_validation_errors_and_authorization(client,db,tmp_path):
    p,v,m=scope(client,db);client.app.state.settings.object_directory=str(tmp_path)
    assert upload(client,v,b'\x00binary').status_code==422
    assert upload(client,v,b'abc','manual.exe').status_code==422
    assert upload(client,v,b'','manual.txt').status_code==422
    authenticate(client,'reader')
    assert upload(client,v).status_code==403
    assert client.get(f'/api/versions/{v}/candidates').status_code==403
    assert not list(tmp_path.iterdir())


def test_invalid_evidence_retry_recovery_and_scope_revocation(client,db,tmp_path):
    from datetime import datetime,timedelta,timezone
    from uuid import UUID
    from sqlalchemy import select
    from knowledge_ai.ingestion.jobs import run_one,ExtractionJob
    from knowledge_ai.profiles.models import KnowledgeVersion
    from knowledge_ai.review.models import Candidate
    p,v,m=scope(client,db);client.app.state.settings.object_directory=str(tmp_path)
    r=upload(client,v).json()
    class Bad:
        def extract(self,chunks,model):
            result=FakeProvider().extract(chunks,model);result['entities'][0]['evidence'][0]['excerpt']='hallucinated';return result
    assert run_one(db,client.app.state.settings,Bad())
    assert client.get('/api/jobs/'+r['job_id']).json()['status']=='queued'
    with db.sessions() as s:
        assert list(s.scalars(select(Candidate)))==[]
        j=s.get(ExtractionJob,UUID(r['job_id']));j.status='running';j.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
    assert run_one(db,client.app.state.settings,FakeProvider())
    assert client.get('/api/jobs/'+r['job_id']).json()['status']=='succeeded'
    r2=upload(client,v,b'Controller changed.').json()
    class Releases:
        def extract(self,chunks,model):
            with db.sessions() as s:
                s.get(KnowledgeVersion,UUID(v)).status='released';s.commit()
            return FakeProvider().extract(chunks,model)
    assert run_one(db,client.app.state.settings,Releases())
    with db.sessions() as s:
        assert s.get(ExtractionJob,UUID(r2['job_id'])).status=='cancelled'
        assert len(list(s.scalars(select(Candidate))))==1


def test_provider_error_and_missing_key_fail_safely(client,db,tmp_path):
    from knowledge_ai.ingestion.jobs import run_one
    from knowledge_ai.ingestion.gemini import ProviderFailure
    p,v,m=scope(client,db);client.app.state.settings.object_directory=str(tmp_path)
    r=upload(client,v).json()
    class Broken:
        def extract(self,*args): raise ProviderFailure('secret-key-private-provider-response')
    run_one(db,client.app.state.settings,Broken())
    detail=client.get('/api/jobs/'+r['job_id']).json()
    assert detail['status']=='queued' and 'secret' not in detail['error']
    from datetime import datetime,timedelta,timezone
    client.app.state.settings.gemini_api_key=''
    run_one(db,client.app.state.settings,now=datetime.now(timezone.utc)+timedelta(seconds=10))
    detail=client.get('/api/jobs/'+r['job_id']).json()
    assert detail['status']=='failed' and 'not configured' in detail['error']

def test_changed_source_revision_and_candidate_content_immutable(client,db,tmp_path):
    import pytest
    from uuid import UUID
    from sqlalchemy import select,text
    from sqlalchemy.exc import DBAPIError
    from knowledge_ai.ingestion.jobs import run_one,ExtractionJob
    from knowledge_ai.review.models import Candidate
    p,v,m=scope(client,db);client.app.state.settings.object_directory=str(tmp_path)
    first=upload(client,v).json()
    second=client.post(f'/api/versions/{v}/sources',files={'file':('manual.txt',b'Controller changed.','text/plain')},data={'source_id':first['source_id']}).json()
    assert second['source_id']==first['source_id'] and second['revision_id']!=first['revision_id'] and second['job_id']!=first['job_id']
    assert run_one(db,client.app.state.settings,FakeProvider())
    with db.sessions() as s:
        c=s.scalar(select(Candidate))
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE draft_candidates SET payload='{}' WHERE id=:id"),{'id':c.id});s.commit()
        s.rollback()
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE source_revisions SET content_hash='bad' WHERE revision_id=:id"),{'id':UUID(first['revision_id'])});s.commit()
        s.rollback()


def test_retry_exhaustion_and_revoked_contribution(client,db,tmp_path):
    from datetime import datetime,timedelta,timezone
    from sqlalchemy import select
    from knowledge_ai.ingestion.jobs import run_one,ExtractionJob
    from knowledge_ai.ingestion.gemini import ProviderFailure
    p,v,m=scope(client,db);client.app.state.settings.object_directory=str(tmp_path)
    r=upload(client,v).json()
    class Broken:
        def extract(self,*args): raise ProviderFailure('private')
    for attempt in range(3):
        run_one(db,client.app.state.settings,Broken(),now=datetime.now(timezone.utc)+timedelta(seconds=100))
    assert client.get('/api/jobs/'+r['job_id']).json()['status']=='failed'
    authenticate(client,'admin')
    from knowledge_ai.db import User
    with db.sessions() as s: cid=str(s.scalar(select(User).where(User.username=='contributor')).id)
    assert client.put(f'/api/profiles/{p}/grants/{cid}',json={'contribute':True}).status_code==200
    authenticate(client,'contributor');r=upload(client,v,b'Controller new.').json()
    authenticate(client,'admin')
    client.put(f'/api/profiles/{p}/grants/{cid}',json={'contribute':False})
    assert run_one(db,client.app.state.settings,FakeProvider())
    assert client.get('/api/jobs/'+r['job_id']).json()['status']=='cancelled'
