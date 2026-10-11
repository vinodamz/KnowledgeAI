from uuid import UUID
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from knowledge_ai.db import get_db
from knowledge_ai.governance.auth import current_actor
from knowledge_ai.governance.policy import authorize
from knowledge_ai.profiles.routes import Input
from knowledge_ai.profiles.service import draft_access
from knowledge_ai.review.routes import ExactPair
from knowledge_ai.publication.models import PublicationJob
from knowledge_ai.publication.builder import request_publication, selected_rows, active

router = APIRouter(prefix='/api')
class PublishInput(Input):
    profile_id: UUID
    version_id: UUID
    candidates: list[ExactPair] = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)

def job_json(job, actor=None):
    result = {'id': str(job.id), 'profile_id': str(job.profile_id), 'version_id': str(job.version_id),
            'status': job.status, 'attempts': job.attempts, 'generation_id': str(job.generation_id) if job.generation_id else None,
            'error': job.error, 'selection': job.selection}
    if actor and actor.role != 'admin' and job.profile_id not in (actor.owned_profile_ids | actor.contribute_profile_ids):
        result.pop('selection'); result.pop('error')
    return result

@router.post('/publications', status_code=202)
def publish(body: PublishInput, actor=Depends(current_actor), db=Depends(get_db)):
    job = request_publication(db, actor, body.profile_id, body.version_id, [x.model_dump() for x in body.candidates], body.idempotency_key)
    db.commit(); return job_json(job)


@router.get('/publications')
def list_jobs(version_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
    from knowledge_ai.profiles.models import KnowledgeVersion
    version = db.get(KnowledgeVersion, version_id)
    if not version: raise HTTPException(404, 'Version not found')
    authorize(actor, 'read', version.profile_id)
    if version.status == 'draft': draft_access(actor, version.profile_id)
    jobs = db.scalars(select(PublicationJob).where(PublicationJob.version_id == version_id).order_by(PublicationJob.created_at.desc()).limit(100))
    return [job_json(job, actor) for job in jobs]

@router.get('/publications/{job_id}')
def status(job_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
    job = db.get(PublicationJob, job_id)
    if not job: raise HTTPException(404, 'Publication job not found')
    authorize(actor, 'read', job.profile_id)
    from knowledge_ai.profiles.models import KnowledgeVersion
    if db.get(KnowledgeVersion, job.version_id).status == 'draft': draft_access(actor, job.profile_id)
    return job_json(job, actor)

@router.post('/publications/{job_id}/retry', status_code=202)
def retry(job_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
    job = db.get(PublicationJob, job_id)
    if not job: raise HTTPException(404, 'Publication job not found')
    selected_rows(db, actor, job.profile_id, job.version_id, job.selection)
    if actor.id != job.actor_id: raise HTTPException(403, 'Original requester required; new owner must create a new publication')
    if job.status != 'publication_failed': raise HTTPException(409, 'Only failed jobs may retry')
    job.status = 'queued'; job.error = None
    db.commit(); return job_json(job)

@router.get('/versions/{version_id}/publication')
def version_publication(version_id: UUID, actor=Depends(current_actor), db=Depends(get_db)):
    from knowledge_ai.profiles.models import KnowledgeVersion
    version = db.get(KnowledgeVersion, version_id)
    if not version: raise HTTPException(404, 'Version not found')
    authorize(actor, 'read', version.profile_id)
    if version.status == 'draft': draft_access(actor, version.profile_id)
    generation = active(db)
    facts = [f for f in generation.scope_manifest['facts'] if f['target_version_id'] == str(version_id)] if generation else []
    return {'generation_id': str(generation.id) if generation else None, 'facts': facts}
