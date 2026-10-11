from uuid import UUID, uuid4
from sqlalchemy import String, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from knowledge_ai.db import Base

class Profile(Base):
    __tablename__ = 'profiles'
    __table_args__ = (CheckConstraint("kind in ('product','project')"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'))
    archived: Mapped[bool] = mapped_column(default=False)

class KnowledgeVersion(Base):
    __tablename__ = 'knowledge_versions'
    __table_args__ = (UniqueConstraint('profile_id','label'), CheckConstraint("status in ('draft','released','archived')"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey('profiles.id'))
    label: Mapped[str] = mapped_column(String(200))
    predecessor_id: Mapped[UUID | None] = mapped_column(ForeignKey('knowledge_versions.id'))
    status: Mapped[str] = mapped_column(String(20), default='draft')

class ProjectDependency(Base):
    __tablename__ = 'project_dependencies'
    project_version_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_versions.id'), primary_key=True)
    product_version_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_versions.id'), primary_key=True)

class ProfileGrant(Base):
    __tablename__ = 'profile_grants'
    profile_id: Mapped[UUID] = mapped_column(ForeignKey('profiles.id'), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), primary_key=True)
    read: Mapped[bool] = mapped_column(default=False)
    contribute: Mapped[bool] = mapped_column(default=False)
