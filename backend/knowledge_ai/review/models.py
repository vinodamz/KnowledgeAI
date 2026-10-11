"""Private review records. Candidate identity is stable; decisions bind revision."""
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, UniqueConstraint, CheckConstraint, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from knowledge_ai.db import Base

class Candidate(Base):
    __tablename__='draft_candidates'
    __table_args__=(UniqueConstraint('id','revision'),CheckConstraint("kind in ('entity','relation','model_suggestion')"),CheckConstraint("state in ('pending','approved','rejected')"))
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    revision: Mapped[int]=mapped_column(primary_key=True,default=1)
    source_revision_id: Mapped[UUID]=mapped_column(ForeignKey('source_revisions.revision_id'))
    kind: Mapped[str]
    payload: Mapped[dict]=mapped_column(JSONB)
    evidence: Mapped[list]=mapped_column(JSONB)
    state: Mapped[str]=mapped_column(default='pending')

class RawExtraction(Base):
    __tablename__='raw_extractions'
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    job_id: Mapped[UUID]=mapped_column(ForeignKey('extraction_jobs.id'),unique=True)
    source_revision_id: Mapped[UUID]=mapped_column(ForeignKey('source_revisions.revision_id'))
    output: Mapped[dict]=mapped_column(JSONB)
