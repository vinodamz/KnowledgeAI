"""Opt-in isolated browser acceptance server; excluded from production Docker."""
import os
if os.environ.get('KNOWLEDGE_AI_UI_TEST')!='1':raise RuntimeError('Explicit UI test opt-in required')
import threading,time,tempfile
from pathlib import Path
from uuid import UUID
import psycopg
from sqlalchemy import text,select
from sqlalchemy.exc import OperationalError
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from knowledge_ai.app import create_app
from knowledge_ai.settings import Settings
from knowledge_ai.db import User
from knowledge_ai.governance.auth import passwords
from knowledge_ai.adapters.lightrag import LightRAGAdapter
from knowledge_ai.ingestion.jobs import run_one as extract_one
from knowledge_ai.publication.worker import run_one as publish_one
from knowledge_ai.retrieval.service import RetrievalService
from knowledge_ai.profiles.models import KnowledgeVersion,Profile,ProfileGrant
from tests.integration.test_review_lifecycle import relation_drafts
from tests.integration.test_publication_generation import deterministic_embeddings
from tests.integration.test_cited_answers import Embed,AnswerProvider
from tests.security.test_profile_owners import authenticate
URL='postgresql+psycopg://postgres:testpassword@127.0.0.1:55432/knowledgeai_ui_test'
with psycopg.connect('postgresql://postgres:testpassword@127.0.0.1:55432/postgres',autocommit=True) as c:
    if not c.execute("SELECT 1 FROM pg_database WHERE datname='knowledgeai_ui_test'").fetchone():c.execute('CREATE DATABASE knowledgeai_ui_test')
os.environ['KNOWLEDGE_AI_DATABASE_URL']=URL
os.environ['KNOWLEDGE_AI_SIGNING_SECRET']='test-only-ui-secret-abcdefghijklmnopqrstuvwxyz'
command.upgrade(Config('alembic.ini'),'head')
work=Path(tempfile.mkdtemp(prefix='knowledge-ai-ui-test-'))
settings=Settings(database_url=URL,signing_secret=os.environ['KNOWLEDGE_AI_SIGNING_SECRET'],object_directory=str(work/'objects'),publication_directory=str(work/'publications'),embedding_dimensions=32,gemini_api_key='')
app=create_app(settings);db=app.state.db
app.state.retrieval_service_factory=lambda db,actor,settings:RetrievalService(db,actor,settings,embedding=Embed(),answer_provider=AnswerProvider())
adapter=LightRAGAdapter(settings,embedding=deterministic_embeddings)
lock=threading.Lock();fail_next=False
class Extraction:
    def extract(self,chunks,model):
        c=chunks[0];e=model['entities'][0];r=model['relations'][0] if model['relations'] else None
        ev=[{'chunk_id':c['chunk_id'],'start':0,'end':min(10,len(c['text'])),'excerpt':c['text'][:10]}]
        return {'entities':[{'key':k,'type_id':e['id'],'type_name':e['name'],'name':k,'attributes':{},'evidence':ev} for k in ('Upload A','Upload B')],'relations':[{'type_id':r['id'],'type_name':r['name'],'source':'Upload A','target':'Upload B','evidence':ev}] if r else []}
def fixture():
    with lock:
        with db.sessions() as s:
            # Previous browser-session requests can still be finishing at reset.
            # Retry only PostgreSQL deadlocks before any fixture writes.
            for attempt in range(3):
                try:
                    s.execute(text('TRUNCATE publication_jobs,active_publication,publication_generations,audit_events,auth_sessions,users CASCADE'))
                    break
                except OperationalError as error:
                    s.rollback()
                    if getattr(error.orig,'sqlstate',None)!='40P01' or attempt==2:raise
                    time.sleep(.1)
            s.execute(text('INSERT INTO active_publication VALUES(1,NULL)'))
            s.add(User(username='admin',role='admin',password_hash=passwords.hash('a-good-test-password')));s.commit()
        client=TestClient(app)
        ids,p,v,es,r=relation_drafts(client,db,work/'objects')
        with db.sessions() as s:
            s.get(Profile,UUID(p)).name='UI Test Product'
            s.get(KnowledgeVersion,UUID(v)).label='1-draft'
            for username in ('reader','contributor'):
                s.add(ProfileGrant(profile_id=UUID(p),user_id=UUID(ids[username]),read=True,contribute=username=='contributor'))
            s.commit()
        original=client.get('/api/versions/'+v).json()
        empty=client.post('/api/profiles/'+p+'/versions',json={'label':'3-empty'}).json()['id']
        client.put('/api/versions/'+empty+'/model',json={'model_revision_id':original['model_revision_id']})
        released=client.post('/api/profiles/'+p+'/versions',json={'label':'2-released'}).json()['id']
        client.put('/api/versions/'+released+'/model',json={'model_revision_id':original['model_revision_id']})
        client.post('/api/versions/'+released+'/sources',files={'file':('test-only.txt',b'Controller test only evidence.','text/plain')})
        assert extract_one(db,settings,Extraction())
        rows=client.get('/api/versions/'+released+'/candidates').json();pairs=[{'candidate_id':c['id'],'revision':c['revision']} for c in rows]
        assert client.post('/api/review/batch',json={'candidates':pairs,'decision':'approve'}).status_code==200
        assert client.post('/api/publications',json={'profile_id':p,'version_id':released,'candidates':pairs,'idempotency_key':'test-seed'}).status_code==202
        assert publish_one(db,settings,adapter)
        with db.sessions() as s:s.get(KnowledgeVersion,UUID(released)).status='released';s.commit()
        return {'profile_id':p,'draft':v,'released':released,'empty':empty,'entities':es,'relation':r}
@app.post('/__test__/reset')
def reset():return fixture()
@app.post('/__test__/fail-publication')
def failure():
    global fail_next
    fail_next=True
    return {'test_only':True}
def worker():
    global fail_next
    while True:
        try:
            with lock:
                extract_one(db,settings,Extraction())
                def fault(boundary):
                    global fail_next
                    if fail_next and boundary=='after_build':fail_next=False;raise RuntimeError('Test-only failure')
                publish_one(db,settings,adapter,fault=fault)
        except Exception as e:print('UI test worker:',type(e).__name__)
        time.sleep(.4)
fixture();threading.Thread(target=worker,daemon=True).start()
