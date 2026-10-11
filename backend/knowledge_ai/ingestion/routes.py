from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request,UploadFile,File,Form
from sqlalchemy import select
from knowledge_ai.db import get_db
from knowledge_ai.governance.auth import current_actor
from knowledge_ai.governance.audit import record_event
from knowledge_ai.profiles.models import KnowledgeVersion
from knowledge_ai.ingestion.sources import SourceRevision
from knowledge_ai.ingestion.jobs import ExtractionJob,lock_scope
from knowledge_ai.ingestion.parser import parse,InvalidSource
from knowledge_ai.adapters.object_store import ObjectStore
from knowledge_ai.review.models import Candidate,RawExtraction
router=APIRouter(prefix='/api')

@router.post('/versions/{version_id}/sources',status_code=201)
async def upload(version_id:UUID,request:Request,file:UploadFile=File(...),source_id:UUID|None=Form(None),actor=Depends(current_actor),db=Depends(get_db)):
    settings=request.app.state.settings
    content=await file.read(settings.upload_max_bytes+1)
    try: name,chunks=parse(content,file.filename or '',settings.upload_max_bytes)
    except InvalidSource as exc: raise HTTPException(422,str(exc))
    version=db.get(KnowledgeVersion,version_id)
    if not version: raise HTTPException(404,'Version not found')
    lock_scope(db,version.profile_id,version.id,version.model_revision_id,actor.id)
    if source_id is not None:
        parent=db.scalar(select(SourceRevision).where(SourceRevision.source_id==source_id,SourceRevision.profile_id==version.profile_id,SourceRevision.knowledge_version_id==version.id).limit(1))
        if not parent: raise HTTPException(404,'Source identity not found in this version')
    key=ObjectStore(settings.object_directory).put(content)
    existing=db.scalar(select(SourceRevision).where(SourceRevision.profile_id==version.profile_id,SourceRevision.knowledge_version_id==version.id,SourceRevision.model_revision_id==version.model_revision_id,SourceRevision.content_hash==key))
    if existing:
        job=db.scalar(select(ExtractionJob).where(ExtractionJob.source_revision_id==existing.revision_id))
        db.commit(); return {'source_id':str(existing.source_id),'revision_id':str(existing.revision_id),'job_id':str(job.id),'duplicate':True}
    source=SourceRevision(profile_id=version.profile_id,knowledge_version_id=version.id,model_revision_id=version.model_revision_id,content_hash=key,object_key=key,provenance={'adapter':'manual','filename':name},access_policy={'scope':'profile','visibility':'private_draft'},uploaded_by=actor.id,chunks=chunks)
    if source_id is not None: source.source_id=source_id
    db.add(source);db.flush()
    job=ExtractionJob(source_revision_id=source.revision_id);db.add(job);db.flush()
    record_event(db,actor.id,'source_uploaded',version.profile_id,{'source_revision_id':str(source.revision_id),'job_id':str(job.id)})
    db.commit()
    return {'source_id':str(source.source_id),'revision_id':str(source.revision_id),'job_id':str(job.id),'duplicate':False}

def authorized_source(db,source,actor):
    if not source: raise HTTPException(404,'Source not found')
    # Raw source and extracted drafts require live content authorization, not read grants.
    lock_scope(db,source.profile_id,source.knowledge_version_id,source.model_revision_id,actor.id,require_draft=False)

@router.get('/sources/{revision_id}')
def source_detail(revision_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    source=db.get(SourceRevision,revision_id);authorized_source(db,source,actor)
    return {'source_id':str(source.source_id),'revision_id':str(source.revision_id),'profile_id':str(source.profile_id),'knowledge_version_id':str(source.knowledge_version_id),'model_revision_id':str(source.model_revision_id),'content_hash':source.content_hash,'provenance':source.provenance,'access_policy':source.access_policy,'chunks':source.chunks}

@router.get('/jobs/{job_id}')
def job_detail(job_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    job=db.get(ExtractionJob,job_id)
    if not job: raise HTTPException(404,'Job not found')
    authorized_source(db,db.get(SourceRevision,job.source_revision_id),actor)
    return {'id':str(job.id),'status':job.status,'attempts':job.attempts,'error':job.error}

@router.get('/versions/{version_id}/candidates')
def candidates(version_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    version=db.get(KnowledgeVersion,version_id)
    if not version: raise HTTPException(404,'Version not found')
    lock_scope(db,version.profile_id,version.id,version.model_revision_id,actor.id,require_draft=False)
    rows=db.scalars(select(Candidate).join(SourceRevision,Candidate.source_revision_id==SourceRevision.revision_id).where(SourceRevision.knowledge_version_id==version_id))
    return [{'id':str(c.id),'revision':c.revision,'kind':c.kind,'payload':c.payload,'evidence':c.evidence,'state':c.state,'source_revision_id':str(c.source_revision_id)} for c in rows]

@router.get('/sources/{revision_id}/extraction')
def raw_extraction(revision_id:UUID,actor=Depends(current_actor),db=Depends(get_db)):
    source=db.get(SourceRevision,revision_id);authorized_source(db,source,actor)
    row=db.scalar(select(RawExtraction).where(RawExtraction.source_revision_id==revision_id))
    if not row: raise HTTPException(404,'Extraction not available')
    return row.output
