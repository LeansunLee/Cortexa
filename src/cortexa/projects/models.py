import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from cortexa.db.engine import Base


class Project(Base):
    __tablename__ = 't_projects'
    __table_args__ = (UniqueConstraint('workspace_id', 'id'), CheckConstraint("status IN ('planned','active','completed','archived')"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('t_workspaces.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(String(2000))
    scope: Mapped[str] = mapped_column(String(4000), default='')
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('t_users.id'))
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('t_users.id'))
    status: Mapped[str] = mapped_column(String(16), default='planned', index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectMember(Base):
    __tablename__ = 't_project_members'
    __table_args__ = (ForeignKeyConstraint(['workspace_id','project_id'],['t_projects.workspace_id','t_projects.id']), UniqueConstraint('project_id','user_id'))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('t_workspaces.id'))
    project_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('t_users.id'))
    role: Mapped[str] = mapped_column(String(16), default='member')


class ProjectActivity(Base):
    __tablename__ = 't_project_activities'
    __table_args__ = (ForeignKeyConstraint(['workspace_id','project_id'],['t_projects.workspace_id','t_projects.id']),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('t_workspaces.id'))
    project_id: Mapped[uuid.UUID]
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('t_users.id'))
    action: Mapped[str] = mapped_column(String(32))
    data_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
