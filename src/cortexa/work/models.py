"""Work tables; source IDs deliberately survive deletion of private chat history."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from cortexa.db.engine import Base


class Identity:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_workspaces.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Work(Identity, Base):
    __tablename__ = "t_works"
    __table_args__ = (
        CheckConstraint("assignee_type IN ('human','agent')"),
        CheckConstraint(
            "status IN ('draft','pending','todo','in_progress','review','completed','rejected','cancelled')"
        ),
        CheckConstraint("priority IN ('P0','P1','P2','P3')"),
        CheckConstraint("source_type IN ('manual','conversation','agent_collaboration','workflow')"),
    )
    title: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(String(2000))
    description: Mapped[str] = mapped_column(String(4000), default="")
    deliverable_requirement: Mapped[str] = mapped_column(String(2000), default="")
    assignee_type: Mapped[str] = mapped_column(String(16), default="human")
    assignee_id: Mapped[uuid.UUID] = mapped_column(index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id"), index=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id"), index=True)
    priority: Mapped[str] = mapped_column(String(4), default="P2")
    status: Mapped[str] = mapped_column(String(24), default="todo", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    source_id: Mapped[uuid.UUID | None]
    source_message_id: Mapped[uuid.UUID | None]
    source_label: Mapped[str] = mapped_column(String(255), default="人工创建")
    source_excerpt: Mapped[str] = mapped_column(String(1000), default="")
    completion_note: Mapped[str] = mapped_column(String(2000), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkCandidate(Identity, Base):
    __tablename__ = "t_work_candidates"
    __table_args__ = (
        UniqueConstraint("conversation_id", "message_id", "fingerprint"),
        CheckConstraint("status IN ('candidate','accepted','rejected')"),
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    message_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(String(2000))
    deliverable_requirement: Mapped[str] = mapped_column(String(2000), default="")
    suggested_assignee_id: Mapped[uuid.UUID | None]
    suggested_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    work_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("t_works.id"))


class WorkDeliverable(Identity, Base):
    __tablename__ = "t_work_deliverables"
    __table_args__ = (CheckConstraint("type IN ('text','file','knowledge','memory')"),)
    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_works.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(String(2000), default="")  # Summary; full text on disk.
    filename: Mapped[str | None] = mapped_column(String(255))
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id"))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class WorkActivity(Identity, Base):
    __tablename__ = "t_work_activities"
    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_works.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="human")
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id"))
    action: Mapped[str] = mapped_column(String(32))
    data_json: Mapped[dict] = mapped_column(JSON, default=dict)
