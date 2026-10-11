"""Manifest construction and activation. No network/index IO while holding row locks."""
import hashlib
import json
from uuid import UUID
from sqlalchemy import select, update
from fastapi import HTTPException
from knowledge_ai.publication.models import PublicationGeneration, ActivePublication, PublicationJob
from knowledge_ai.review.service import locked_candidates, publication_readiness, checksum
from knowledge_ai.governance.policy import Actor
from knowledge_ai.governance.audit import record_event


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def active(db):
    pointer = db.get(ActivePublication, 1)
    return db.get(PublicationGeneration, pointer.generation_id) if pointer and pointer.generation_id else None


def selected_rows(db, actor, profile_id, version_id, selection):
    rows, sources = locked_candidates(db, actor, [(UUID(x['candidate_id']), x['revision']) for x in selection])
    if any((s.profile_id, s.knowledge_version_id) != (profile_id, version_id) for s in sources.values()):
        raise HTTPException(422, 'Publication selection must match the requested profile and version')
    for item in selection:
        if item.get('checksum') and item['checksum'] != checksum(rows[UUID(item['candidate_id'])]):
            raise HTTPException(409, 'Selected approved revision changed')
    return rows, sources


def make_manifest(db, actor, profile_id, version_id, selection, previous):
    rows, sources = selected_rows(db, actor, profile_id, version_id, selection)
    # Exact prior facts remain immutable even when a newer draft revision exists.
    facts = list(previous.scope_manifest['facts']) if previous else []
    selected_ids = {str(c.id) for c in rows.values()}
    # Keep old endpoint revisions if retained relations still reference them.
    required = set()
    for f in facts:
        if f['kind'] == 'relation' and f['candidate_id'] not in selected_ids:
            for side in ('source', 'target'):
                required.add((f['payload'][f'{side}_candidate_id'], f['payload'][f'{side}_candidate_revision']))
    facts = [f for f in facts if f['candidate_id'] not in selected_ids or (f['candidate_id'], f['revision']) in required]
    for c in rows.values():
        s = sources[c.id]
        facts = [f for f in facts if (f['candidate_id'], f['revision']) != (str(c.id), c.revision)]
        facts.append({'candidate_id': str(c.id), 'revision': c.revision, 'kind': c.kind,
                      'checksum': checksum(c), 'payload': c.payload, 'evidence': c.evidence,
                      'source_revision_id': str(s.revision_id), 'model_revision_id': str(s.model_revision_id),
                      'source_profile_id': str(s.profile_id), 'source_version_id': str(s.knowledge_version_id),
                      'target_profile_id': str(profile_id), 'target_version_id': str(version_id)})
    pairs = {(UUID(f['candidate_id']), f['revision']) for f in facts}
    for c in rows.values():
        readiness = publication_readiness(db, c, target_manifest=pairs)
        if not readiness['ready']:
            raise HTTPException(409, '; '.join(readiness['blockers']))
    manifest = {'schema': 1, 'representation': 'typed-directed-relation-ports-v1',
                'facts': sorted(facts, key=lambda f: (f['target_version_id'], f['candidate_id'], f['revision']))}
    validate_closure(manifest)
    return manifest


def validate_closure(manifest):
    entities = {(f['target_version_id'], f['candidate_id'], f['revision']) for f in manifest['facts'] if f['kind'] == 'entity'}
    for f in manifest['facts']:
        if f['kind'] == 'relation':
            for side in ('source', 'target'):
                if (f['target_version_id'], f['payload'][f'{side}_candidate_id'], f['payload'][f'{side}_candidate_revision']) not in entities:
                    raise HTTPException(409, 'Target manifest lacks exact scoped entity endpoint')
        elif f['kind'] != 'entity':
            raise HTTPException(409, 'Non-instance fact in publication')


def request_publication(db, actor, profile_id, version_id, selection, key):
    normalized = sorted([{'candidate_id': str(x['candidate_id']), 'revision': x['revision']} for x in selection], key=lambda x:x['candidate_id'])
    # Validate live assigned ownership even for idempotent repeats.
    rows, _ = selected_rows(db, actor, profile_id, version_id, normalized)
    old = db.scalar(select(PublicationJob).where(PublicationJob.actor_id == actor.id, PublicationJob.idempotency_key == key))
    if old:
        if old.profile_id != profile_id or old.version_id != version_id or [{k:x[k] for k in ('candidate_id','revision')} for x in old.selection] != normalized:
            raise HTTPException(409, 'Idempotency key already used for a different request')
        return old
    make_manifest(db, actor, profile_id, version_id, normalized, active(db))
    for item in normalized: item['checksum'] = checksum(rows[UUID(item['candidate_id'])])
    job = PublicationJob(actor_id=actor.id, profile_id=profile_id, version_id=version_id, selection=normalized, idempotency_key=key)
    db.add(job); db.flush()
    record_event(db, actor.id, 'publication_requested', profile_id, {'job_id': str(job.id), 'selection': normalized})
    return job


def activate_generation(db, generation_id, expected_active_id, job):
    generation = db.get(PublicationGeneration, generation_id)
    if not generation or generation.status != 'verified' or not generation.verification or generation.verification['manifest_digest'] != digest(generation.scope_manifest):
        raise HTTPException(409, 'Generation lacks verified index report')
    prior = db.get(PublicationGeneration, expected_active_id) if expected_active_id else None
    rebuilt = make_manifest(db, Actor(job.actor_id, 'owner'), job.profile_id, job.version_id, job.selection, prior)
    if rebuilt != generation.scope_manifest: raise HTTPException(409, 'Registry manifest changed during build')
    job = db.scalar(select(PublicationJob).where(PublicationJob.id == job.id).with_for_update().execution_options(populate_existing=True))
    if job.status != 'building' or job.generation_id != generation_id or job.expected_active_id != expected_active_id:
        raise HTTPException(409, 'Publisher attempt was superseded')
    result = db.execute(update(ActivePublication).where(ActivePublication.singleton == 1, ActivePublication.generation_id == expected_active_id).values(generation_id=generation_id))
    if result.rowcount != 1: raise HTTPException(409, 'Active generation changed; rebuild required')
    if prior: prior.status = 'retired'
    generation.status = 'active'; job.status = 'published'; job.error = None
    record_event(db, job.actor_id, 'publication_activated', job.profile_id, {'generation_id': str(generation_id), 'manifest_digest': digest(rebuilt)})
