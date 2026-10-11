"""Model definitions are revision-scoped, separate from knowledge instances."""
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from knowledge_ai.db import Base

class KnowledgeModelRevision(Base):
    __tablename__='knowledge_model_revisions'
    __table_args__=(UniqueConstraint('profile_id','revision'),CheckConstraint("status in ('draft','published')"))
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    profile_id: Mapped[UUID]=mapped_column(ForeignKey('profiles.id'))
    revision: Mapped[int]
    status: Mapped[str]=mapped_column(String(20),default='draft')
    semantic_description: Mapped[str]=mapped_column(default='')

class EntityType(Base):
    __tablename__='entity_types'
    __table_args__=(UniqueConstraint('model_revision_id','name'),)
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    model_revision_id: Mapped[UUID]=mapped_column(ForeignKey('knowledge_model_revisions.id'))
    name: Mapped[str]=mapped_column(String(200))
    attributes: Mapped[list]=mapped_column(JSONB,default=list)
    scores: Mapped[dict]=mapped_column(JSONB,default=dict)
    qualification: Mapped[str | None]
    qualified_by: Mapped[UUID | None]=mapped_column(ForeignKey('users.id'))

class RelationType(Base):
    __tablename__='relation_types'
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    model_revision_id: Mapped[UUID]=mapped_column(ForeignKey('knowledge_model_revisions.id'))
    source_type_id: Mapped[UUID]=mapped_column(ForeignKey('entity_types.id'))
    target_type_id: Mapped[UUID]=mapped_column(ForeignKey('entity_types.id'))
    name: Mapped[str]=mapped_column(String(200))

class CanonicalConcept(Base):
    __tablename__='canonical_concepts'
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    profile_id: Mapped[UUID]=mapped_column(ForeignKey('profiles.id'))
    model_revision_id: Mapped[UUID]=mapped_column(ForeignKey('knowledge_model_revisions.id'))
    name: Mapped[str]=mapped_column(String(200))
    aliases: Mapped[list]=mapped_column(JSONB,default=list)
    provenance: Mapped[dict]=mapped_column(JSONB,default=dict)

class ModelLink(Base):
    __tablename__='model_links'
    model_revision_id: Mapped[UUID]=mapped_column(ForeignKey('knowledge_model_revisions.id'),primary_key=True)
    target_model_revision_id: Mapped[UUID]=mapped_column(ForeignKey('knowledge_model_revisions.id'),primary_key=True)
