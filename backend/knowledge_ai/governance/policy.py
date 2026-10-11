from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID
from fastapi import HTTPException

Role = Literal['admin', 'owner', 'contributor', 'reader']
@dataclass(frozen=True)
class Actor:
    id: UUID
    role: Role
    owned_profile_ids: frozenset[UUID] = field(default_factory=frozenset)
    read_profile_ids: frozenset[UUID] = field(default_factory=frozenset)
    contribute_profile_ids: frozenset[UUID] = field(default_factory=frozenset)

def authorize(actor: Actor, action: str, profile_id: UUID | None) -> None:
    # Unknown actions fail closed, even for administrators.
    if action not in {'create_profile','assign_owner','read','write','review','publish'}:
        raise HTTPException(403, 'Unknown policy action')
    if action in {'create_profile','assign_owner'}:
        allowed = actor.role == 'admin'
    elif action in {'review','publish'}:
        allowed = actor.role in {'owner', 'admin'} and profile_id in actor.owned_profile_ids
    elif action == 'read':
        allowed = actor.role == 'admin' or profile_id in (actor.owned_profile_ids | actor.read_profile_ids | actor.contribute_profile_ids)
    else:
        allowed = actor.role == 'admin' or (actor.role in {'owner', 'admin'} and profile_id in actor.owned_profile_ids) or (actor.role == 'contributor' and profile_id in actor.contribute_profile_ids)
    if not allowed:
        raise HTTPException(403, 'Scope does not permit this action')
