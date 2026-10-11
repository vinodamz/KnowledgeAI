"""Durable leased extraction, network work outside registry transactions."""
from datetime import datetime,timedelta,timezone
from uuid import UUID,uuid4
from sqlalchemy import ForeignKey,DateTime,CheckConstraint,select,or_,and_
from sqlalchemy.orm import Mapped,mapped_column
from fastapi import HTTPException
from knowledge_ai.db import Base,User
from knowledge_ai.profiles.models import Profile,KnowledgeVersion,ProfileGrant
from knowledge_ai.ontology.models import KnowledgeModelRevision,EntityType,RelationType,CanonicalConcept
from knowledge_ai.governance.policy import Actor,authorize
from knowledge_ai.ingestion.sources import SourceRevision
from knowledge_ai.ingestion.extraction import validate_output
from knowledge_ai.ingestion.gemini import GeminiProvider,ProviderFailure
from knowledge_ai.review.models import RawExtraction

class ExtractionJob(Base):
    __tablename__='extraction_jobs'
    __table_args__=(CheckConstraint("status in ('queued','running','succeeded','failed','cancelled')"),)
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    source_revision_id: Mapped[UUID]=mapped_column(ForeignKey('source_revisions.revision_id'),unique=True)
    status: Mapped[str]=mapped_column(default='queued')
    attempts: Mapped[int]=mapped_column(default=0)
    available_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    lease_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID|None]
    error: Mapped[str|None]

def lock_scope(db,profile_id,version_id,model_id,actor_id,*,require_draft=True):
    profile=db.scalar(select(Profile).where(Profile.id==profile_id).with_for_update().execution_options(populate_existing=True))
    version=db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.id==version_id).with_for_update().execution_options(populate_existing=True))
    user=db.scalar(select(User).where(User.id==actor_id).with_for_update().execution_options(populate_existing=True))
    grant=db.scalar(select(ProfileGrant).where(ProfileGrant.profile_id==profile_id,ProfileGrant.user_id==actor_id).with_for_update().execution_options(populate_existing=True))
    if not profile or profile.archived or not user or not user.active: raise HTTPException(403,'Source scope is unavailable')
    actor=Actor(user.id,user.role,frozenset({profile.id}) if profile.owner_id==user.id else frozenset(),contribute_profile_ids=frozenset({profile.id}) if grant and grant.contribute else frozenset())
    authorize(actor,'write',profile.id)
    model=db.get(KnowledgeModelRevision,model_id) if model_id else None
    if not version or version.profile_id!=profile_id or (require_draft and (version.status!='draft' or version.model_revision_id!=model_id)) or not model or model.profile_id!=profile_id or model.status!='published': raise HTTPException(409,'Extraction requires a draft version bound to its exact published model')
    return version

def model_payload(db,model_id):
    return {'id':str(model_id),'profile_id':str(db.get(KnowledgeModelRevision,model_id).profile_id),'semantic_description':db.get(KnowledgeModelRevision,model_id).semantic_description,'concepts':[{'id':str(c.id),'profile_id':str(c.profile_id),'name':c.name,'aliases':c.aliases} for c in db.scalars(select(CanonicalConcept).where(CanonicalConcept.model_revision_id==model_id))],'entities':[{'id':str(e.id),'name':e.name,'attributes':e.attributes} for e in db.scalars(select(EntityType).where(EntityType.model_revision_id==model_id))],'relations':[{'id':str(r.id),'name':r.name,'source_type_id':str(r.source_type_id),'target_type_id':str(r.target_type_id)} for r in db.scalars(select(RelationType).where(RelationType.model_revision_id==model_id))]}

def run_one(database,settings,provider=None,now=None):
    now=now or datetime.now(timezone.utc)
    token=uuid4()
    with database.sessions() as db:
        with db.begin():
            job=db.scalar(select(ExtractionJob).where(or_(and_(ExtractionJob.status=='queued',ExtractionJob.available_at<=now),and_(ExtractionJob.status=='running',ExtractionJob.lease_until<=now))).order_by(ExtractionJob.available_at).limit(1))
            if not job: return False
            source=db.get(SourceRevision,job.source_revision_id)
            try: lock_scope(db,source.profile_id,source.knowledge_version_id,source.model_revision_id,source.uploaded_by)
            except HTTPException:
                job=db.scalar(select(ExtractionJob).where(ExtractionJob.id==job.id).with_for_update(skip_locked=True))
                if job: job.status='cancelled'; job.error='Source author or draft scope is no longer authorized'
                return True
            job=db.scalar(select(ExtractionJob).where(ExtractionJob.id==job.id,or_(and_(ExtractionJob.status=='queued',ExtractionJob.available_at<=now),and_(ExtractionJob.status=='running',ExtractionJob.lease_until<=now))).with_for_update(skip_locked=True).execution_options(populate_existing=True))
            if not job: return False
            if job.attempts>=3:
                job.status='failed'; job.error='Extraction retry limit reached'; return True
            job.status='running'; job.attempts+=1; job.lease_token=token; job.lease_until=now+timedelta(seconds=180)
            jid=job.id; model=model_payload(db,source.model_revision_id)
        # Detached immutable source/chunks survive commit; no database locks during HTTP.
    try:
        output=(provider or GeminiProvider(settings)).extract(source.chunks,model)
        candidates,raw=validate_output(source,model,output)
        error=None
    except ProviderFailure as exc:
        error='Gemini API key is not configured' if provider is None and not settings.gemini_api_key else 'Extraction provider unavailable'
    except Exception:
        error='Extraction output failed model or evidence validation'
    with database.sessions() as db:
        with db.begin():
            # Same profile-first order as all profile/content mutations.
            try: lock_scope(db,source.profile_id,source.knowledge_version_id,source.model_revision_id,source.uploaded_by)
            except HTTPException: error='Source author or draft scope is no longer authorized'
            job=db.scalar(select(ExtractionJob).where(ExtractionJob.id==jid).with_for_update().execution_options(populate_existing=True))
            if not job or job.status!='running' or job.lease_token!=token or job.lease_until<=datetime.now(timezone.utc): return True
            job.lease_until=None; job.lease_token=None
            if error:
                job.error=error
                if error.startswith('Source author'): job.status='cancelled'
                elif job.attempts>=3 or 'not configured' in error: job.status='failed'
                else: job.status='queued'; job.available_at=datetime.now(timezone.utc)+timedelta(seconds=2**job.attempts)
            else:
                db.add_all(candidates); db.add(RawExtraction(job_id=jid,source_revision_id=source.revision_id,output=raw)); job.status='succeeded'; job.error=None
    return True
