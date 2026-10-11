"""Publication-only indexing port. Concrete LightRAG implementation arrives in Task 6."""
from dataclasses import dataclass
from typing import Protocol, Sequence, Mapping, Any
from uuid import UUID

@dataclass(frozen=True)
class IndexReport:
    generation_id: UUID
    entity_count: int
    relation_count: int
    evidence_count: int
    verified: bool

class IndexAdapter(Protocol):
    def build(self, generation_id: UUID, approved_entities: Sequence[Mapping[str, Any]],
              approved_relations: Sequence[Mapping[str, Any]],
              approved_evidence: Sequence[Mapping[str, Any]]) -> IndexReport:
        """Build isolated staging stores from an approved manifest, never activate them."""
        ...
