"""One PostgreSQL session advisory lock fences all publishers, including crash recovery.

Network/index work runs without row locks or an open transaction on the lock
connection. A lost process releases the lock; its building job is rebuilt into a
new generation. Activation and success status share one registry transaction.
"""
import logging
from sqlalchemy import select, text
from knowledge_ai.publication.models import PublicationJob, PublicationGeneration
from knowledge_ai.publication.builder import active, make_manifest, activate_generation
from knowledge_ai.governance.policy import Actor
from knowledge_ai.adapters.lightrag import LightRAGAdapter

logger = logging.getLogger(__name__)
WRITER_LOCK = 76493061


def run_one(database, settings, adapter=None, fault=None):
    fault = fault or (lambda boundary: None)
    with database.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': WRITER_LOCK}): return False
        try:
            with database.sessions() as db:
                job = db.scalar(select(PublicationJob).where(PublicationJob.status.in_(['queued','building'])).order_by(PublicationJob.created_at).limit(1))
                if not job: return False
                jid = job.id
                gid = None
            try:
                with database.sessions() as db, db.begin():
                    job = db.get(PublicationJob, jid)
                    # Previous staging is never reused, including after hard interruption.
                    if job.generation_id:
                        old = db.get(PublicationGeneration, job.generation_id)
                        if old and old.status in {'staging','verified'}: old.status = 'failed'
                    prior = active(db)
                    manifest = make_manifest(db, Actor(job.actor_id, 'owner'), job.profile_id, job.version_id, job.selection, prior)
                    generation = PublicationGeneration(scope_manifest=manifest)
                    db.add(generation); db.flush()
                    gid = generation.id
                    job.generation_id = gid; job.expected_active_id = prior.id if prior else None
                    job.status = 'building'; job.attempts += 1; job.error = None
                fault('after_staging_commit')
                adapter = adapter or LightRAGAdapter(settings)
                report = adapter.build_generation(gid, manifest)
                fault('after_build')
                adapter.verify_seal(gid, report)
                with database.sessions() as db, db.begin():
                    current_job = db.scalar(select(PublicationJob).where(PublicationJob.id == jid).with_for_update().execution_options(populate_existing=True))
                    if current_job.generation_id != gid or current_job.status != 'building': raise RuntimeError('Publisher attempt superseded')
                    generation = db.get(PublicationGeneration, gid)
                    generation.verification = report; generation.status = 'verified'
                fault('after_verification_commit')
                fault('before_activation')
                adapter.verify_seal(gid, report)
                with database.sessions() as db, db.begin():
                    job = db.get(PublicationJob, jid)
                    # The same live session must still own the global writer lock.
                    if lock.invalidated: raise RuntimeError('Publisher lock connection lost')
                    if not lock.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=:key AND granted)"), {'key': WRITER_LOCK}):
                        raise RuntimeError('Publisher no longer owns writer lock')
                    activate_generation(db, gid, job.expected_active_id, job)
                    fault('before_activation_commit')
                fault('after_activation_commit')
            except Exception:
                # No raw engine errors, source text, credentials or provider responses in logs/API.
                logger.error('publication_failed job_id=%s category=build_verification_or_registry_conflict', jid)
                with database.sessions() as db, db.begin():
                    job = db.get(PublicationJob, jid)
                    # A failure after commit must not label an active generation as failed.
                    if job.status != 'published' and (gid is None or job.generation_id == gid):
                        job.status = 'publication_failed'; job.error = 'Publication failed verification or scope changed; retry rebuilds from approved registry'
                        if job.generation_id:
                            generation = db.get(PublicationGeneration, job.generation_id)
                            if generation and generation.status in {'staging','verified'}: generation.status = 'failed'
            return True
        finally:
            if not lock.invalidated:
                lock.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': WRITER_LOCK})
