from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from knowledge_ai.db import Base

class PublicationGeneration(Base):
    __tablename__ = 'publication_generations'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_manifest: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default='staging')
    verification: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ActivePublication(Base):
    __tablename__ = 'active_publication'
    singleton: Mapped[int] = mapped_column(primary_key=True, default=1)
    generation_id: Mapped[UUID | None] = mapped_column(ForeignKey('publication_generations.id'))

class PublicationJob(Base):
    __tablename__ = 'publication_jobs'
    __table_args__ = (UniqueConstraint('actor_id', 'idempotency_key'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'))
    profile_id: Mapped[UUID] = mapped_column(ForeignKey('profiles.id'))
    version_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_versions.id'))
    idempotency_key: Mapped[str]
    selection: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default='queued')
    attempts: Mapped[int] = mapped_column(default=0)
    generation_id: Mapped[UUID | None] = mapped_column(ForeignKey('publication_generations.id'))
    expected_active_id: Mapped[UUID | None] = mapped_column(ForeignKey('publication_generations.id'))
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
