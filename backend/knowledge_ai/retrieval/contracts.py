"""Internal context is server resolved; public requests supply only profile/version/query."""
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class RetrievalContext:
    actor_id: UUID
    profile_id: UUID
    knowledge_version_id: UUID
    generation_id: UUID | None
    allowed_version_ids: tuple[UUID, ...]

@dataclass(frozen=True)
class KnowledgeContext:
    items: tuple[dict, ...]
    citations: tuple[dict, ...]
    model_versions: tuple[str, ...]
    policy_context: dict

@dataclass(frozen=True)
class Answer:
    status: str
    text: str
    citations: tuple[dict, ...]
    context: KnowledgeContext

# Explicit API schemas keep Angular clients aware of version/provenance fields.
from pydantic import BaseModel
from typing import Literal

class CitationResponse(BaseModel):
    id: str
    candidate_id: UUID
    candidate_revision: int
    profile_id: UUID
    profile_kind: Literal['product','project']
    profile_name: str
    version_id: UUID
    version_label: str
    version_status: Literal['draft','released','archived']
    product_version_id: UUID | None
    project_version_id: UUID | None
    source_profile_id: UUID
    source_version_id: UUID
    model_revision_id: UUID
    source_id: UUID
    source_revision_id: UUID
    provenance: dict
    reviewer_id: UUID
    review_decision_id: UUID
    approval_checksum: str
    evidence: list[dict]

class ItemResponse(BaseModel):
    id: str
    approved: Literal[True]
    version_id: UUID
    kind: Literal['entity','relation']
    payload: dict
    claim: str
    score: float
    canonical_concept_id: UUID | None
    attribution: CitationResponse

class PolicyResponse(BaseModel):
    generation_id: UUID | None
    profile_id: UUID
    knowledge_version_id: UUID
    allowed_version_ids: list[UUID]
    approved_only: Literal[True]
    conflicts: list[dict]
    implementation_overrides: list[dict]

class KnowledgeResponse(BaseModel):
    items: list[ItemResponse]
    citations: list[CitationResponse]
    model_versions: list[UUID]
    policy_context: PolicyResponse

class AnswerResponse(BaseModel):
    status: Literal['answered','insufficient_knowledge']
    text: str
    citations: list[CitationResponse]
    context: KnowledgeResponse

class EdgeResponse(ItemResponse):
    source: str
    target: str
    type_id: UUID
    directed: Literal[True]

class GraphResponse(BaseModel):
    nodes: list[ItemResponse]
    edges: list[EdgeResponse]
    citations: list[CitationResponse]
    contexts: list[PolicyResponse]

class AvailableContextResponse(BaseModel):
    profile_id: UUID
    profile_name: str
    profile_kind: Literal['product','project']
    version_id: UUID
    version_label: str
    version_status: Literal['draft','released','archived']
