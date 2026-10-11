from datetime import datetime, timezone
from knowledge_ai.db import AuditEvent

def record_event(db, actor_id, action, profile_id=None, details=None):
    event = AuditEvent(actor_id=actor_id, action=action, profile_id=profile_id,
                       details=details or {}, created_at=datetime.now(timezone.utc))
    db.add(event)
    return event
