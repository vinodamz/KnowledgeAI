"""Scoped activity, excluding private draft events for read-only grants."""
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select, or_, and_
from knowledge_ai.db import get_db, AuditEvent
from knowledge_ai.governance.auth import current_actor
from knowledge_ai.governance.policy import authorize
router = APIRouter(prefix='/api')
@router.get('/activity')
def activity(profile_id: UUID | None = None, actor=Depends(current_actor), db=Depends(get_db)):
    query = select(AuditEvent)
    if profile_id is not None:
        authorize(actor, 'read', profile_id)
        query = query.where(AuditEvent.profile_id == profile_id)
    private = actor.owned_profile_ids | actor.contribute_profile_ids
    if actor.role != 'admin':
        query = query.where(or_(AuditEvent.profile_id.in_(private), and_(AuditEvent.profile_id.in_(actor.read_profile_ids), AuditEvent.action.in_(['publication_activated','version_released','version_archived']))))
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(200))
    return [{'id':str(e.id),'action':e.action,'profile_id':str(e.profile_id) if e.profile_id else None,'actor_id':str(e.actor_id) if e.actor_id else None,'created_at':e.created_at.isoformat(),'details':e.details if actor.role == 'admin' or e.profile_id in private else {}} for e in rows]
