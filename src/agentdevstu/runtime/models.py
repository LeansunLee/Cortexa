"""Approved Phase 3 checkpoint schema; never created automatically at startup."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentdevstu.db.engine import Base


class RuntimeGoal(Base):
    __tablename__ = "t_runtime_goals"
    __table_args__ = (
        UniqueConstraint("workspace_id", "owner_user_id", "idempotency_key", name="uq_runtime_goal_request"),
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["t_agents.workspace_id", "t_agents.id"],
            ondelete="RESTRICT",
            name="fk_runtime_goal_agent",
        ),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="ck_runtime_goal_key"),
        CheckConstraint("status IN ('RUNNING','COMPLETE','BLOCKED','WAITING','FAILED')", name="ck_runtime_goal_status"),
        CheckConstraint("revision > 0", name="ck_runtime_goal_revision"),
        CheckConstraint("jsonb_typeof(state) = 'object'", name="ck_runtime_goal_state"),
        CheckConstraint("jsonb_typeof(artifacts) = 'object'", name="ck_runtime_goal_artifacts"),
        Index("ix_runtime_goal_conversation", "workspace_id", "owner_user_id", "conversation_id", "updated_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_workspaces.id", ondelete="CASCADE"))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id", ondelete="RESTRICT"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_conversations.id", ondelete="CASCADE"))
    initial_message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_conversation_messages.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID]
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), server_default="RUNNING")
    revision: Mapped[int] = mapped_column(server_default="1")
    state: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    artifacts: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
