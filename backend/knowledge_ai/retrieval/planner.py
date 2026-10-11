"""Authorize all exact dependencies before opening ANY publication store."""
from uuid import UUID
from sqlalchemy import select
from fastapi import HTTPException
from knowledge_ai.db import User
from knowledge_ai.governance.policy import Actor, authorize
from knowledge_ai.profiles.models import Profile, ProfileGrant, KnowledgeVersion, ProjectDependency
from knowledge_ai.profiles.service import draft_access
from knowledge_ai.publication.reader import pin_generation
from .contracts import RetrievalContext

def live_actor(db, actor):
    user = db.get(User, actor.id, populate_existing=True)
    if not user or not user.active: raise HTTPException(403, 'Active identity required')
    owned = frozenset(db.scalars(select(Profile.id).where(Profile.owner_id == user.id)))
    grants = list(db.scalars(select(ProfileGrant).where(ProfileGrant.user_id == user.id).execution_options(populate_existing=True)))
    return Actor(user.id, user.role, owned, frozenset(g.profile_id for g in grants if g.read), frozenset(g.profile_id for g in grants if g.contribute))

def check_version(db, actor, version_id, profile_id=None):
    version = db.get(KnowledgeVersion, version_id, populate_existing=True)
    if not version: raise HTTPException(404, 'Version not found')
    if profile_id is not None and version.profile_id != profile_id: raise HTTPException(422, 'Profile/version mismatch')
    authorize(actor, 'read', version.profile_id)
    if version.status == 'draft': draft_access(actor, version.profile_id)
    return version

_UNPINNED = object()

def resolve_context(db, actor, profile_id, version_id, *, pinned_generation=_UNPINNED):
    actor = live_actor(db, actor)
    version = check_version(db, actor, version_id, profile_id)
    dependencies = tuple(db.scalars(select(ProjectDependency.product_version_id).where(ProjectDependency.project_version_id == version.id).order_by(ProjectDependency.product_version_id)))
    for dependency in dependencies: check_version(db, actor, dependency)
    generation = pin_generation(db) if pinned_generation is _UNPINNED else pinned_generation
    return RetrievalContext(actor.id, profile_id, version.id, generation, (version.id,) + dependencies)

def validate_context(db, actor, context):
    if actor.id != context.actor_id: raise HTTPException(403, 'Context identity mismatch')
    actor = live_actor(db, actor)
    check_version(db, actor, context.knowledge_version_id, context.profile_id)
    expected = (context.knowledge_version_id,) + tuple(db.scalars(select(ProjectDependency.product_version_id).where(ProjectDependency.project_version_id == context.knowledge_version_id).order_by(ProjectDependency.product_version_id)))
    if context.allowed_version_ids != expected: raise HTTPException(409, 'Pinned dependencies changed')
    for version in expected: check_version(db, actor, version)
    return actor
