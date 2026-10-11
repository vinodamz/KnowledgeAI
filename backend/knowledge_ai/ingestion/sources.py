from uuid import UUID, uuid4
from typing import Protocol
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from knowledge_ai.db import Base

class SourceRevision(Base):
    __tablename__='source_revisions'
    __table_args__=(UniqueConstraint('profile_id','knowledge_version_id','model_revision_id','content_hash'),)
    revision_id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    source_id: Mapped[UUID]=mapped_column(default=uuid4)
    profile_id: Mapped[UUID]=mapped_column(ForeignKey('profiles.id'))
    knowledge_version_id: Mapped[UUID]=mapped_column(ForeignKey('knowledge_versions.id'))
    model_revision_id: Mapped[UUID]=mapped_column(ForeignKey('knowledge_model_revisions.id'))
    content_hash: Mapped[str]
    object_key: Mapped[str]
    provenance: Mapped[dict]=mapped_column(JSONB)
    access_policy: Mapped[dict]=mapped_column(JSONB)
    uploaded_by: Mapped[UUID]=mapped_column(ForeignKey('users.id'))
    chunks: Mapped[list]=mapped_column(JSONB)

class SourceAdapter(Protocol):
    def fetch_revision(self, source_id: UUID, revision_id: UUID) -> SourceRevision: ...

class ManualSourceAdapter:
    def __init__(self, db): self.db=db
    def fetch_revision(self, source_id, revision_id):
        row=self.db.get(SourceRevision,revision_id)
        if row is None or row.source_id!=source_id: raise LookupError('Source revision not found')
        return row
