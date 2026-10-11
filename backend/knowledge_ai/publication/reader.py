"""Task7 boundary: resolve authorization BEFORE selecting any physical index.

Pin a generation once per request and pass its ID throughout retrieval/citation
work. Retired generations remain readable by already pinned requests. Staging,
failed and merely verified generations are never readable through this boundary.
"""
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
from fastapi import HTTPException
from knowledge_ai.governance.policy import authorize
from knowledge_ai.profiles.models import KnowledgeVersion
from knowledge_ai.profiles.service import draft_access
from knowledge_ai.publication.models import PublicationGeneration
from knowledge_ai.publication.builder import active, digest
from knowledge_ai.adapters.lightrag import files_digest, embedding_identity

@dataclass(frozen=True)
class VerifiedPartition:
    generation_id: UUID
    version_id: UUID
    directory: Path
    workspace: str
    facts: tuple
    manifest_digest: str


def pin_generation(db):
    generation = active(db)
    return generation.id if generation else None


def verified_partition(db, actor, settings, generation_id, version_id):
    version = db.get(KnowledgeVersion, version_id)
    if not version: raise HTTPException(404, 'Version not found')
    authorize(actor, 'read', version.profile_id)
    if version.status == 'draft': draft_access(actor, version.profile_id)
    generation = db.get(PublicationGeneration, generation_id)
    if not generation or generation.status not in {'active','retired'} or not generation.verification:
        raise HTTPException(404, 'Published generation not found')
    if digest(generation.scope_manifest) != generation.verification['manifest_digest']:
        raise HTTPException(503, 'Publication verification failed')
    try:
        compatible = generation.verification.get('embedding') == embedding_identity(settings)
    except ValueError:
        compatible = False
    if not compatible: raise HTTPException(503, 'Published embedding configuration incompatible')
    partition = generation.verification['partitions'].get(str(version_id))
    if not partition: return None
    if partition['profile_id'] != str(version.profile_id): raise HTTPException(503, 'Partition attribution mismatch')
    directory = Path(settings.publication_directory) / str(generation.id)
    path = directory / partition['workspace']
    if files_digest(path) != partition['digest']: raise HTTPException(503, 'Published index unavailable or changed')
    facts = tuple(f for f in generation.scope_manifest['facts'] if f['target_version_id'] == str(version_id))
    return VerifiedPartition(generation.id, version_id, directory, partition['workspace'], facts, generation.verification['manifest_digest'])
