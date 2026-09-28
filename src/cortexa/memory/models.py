"""Memory governance records; sources remain permission-controlled references."""

import uuid
from datetime import datetime
from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    CheckConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from cortexa.db.engine import Base


class Identity:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def memory_fk(name):
    return ForeignKeyConstraint(
        ["workspace_id", "agent_id", "memory_id"],
        ["t_memories.workspace_id", "t_memories.agent_id", "t_memories.id"],
        name=name,
        ondelete="CASCADE",
    )


class MemoryEvidence(Identity, Base):
    __tablename__ = "t_memory_evidences"
    __table_args__ = (
        memory_fk("fk_evidence_memory"),
        UniqueConstraint("memory_id", "evidence_key", name="uq_evidence_key"),
        Index("ix_evidence_source", "workspace_id", "source_type", "source_id", "source_sub_id"),
    )
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(128))
    source_sub_type: Mapped[str | None] = mapped_column(String(64))
    source_sub_id: Mapped[str | None] = mapped_column(String(128))
    source_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_users.id", ondelete="SET NULL")
    )
    source_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id", ondelete="SET NULL")
    )
    source_mode: Mapped[str | None] = mapped_column(String(32))
    stance: Mapped[str] = mapped_column(String(16), default="supports")
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_status: Mapped[str] = mapped_column(String(32), default="available")
    source_revision: Mapped[str | None] = mapped_column(String(128))
    evidence_key: Mapped[str] = mapped_column(String(64))
    root_keys: Mapped[list] = mapped_column(JSONB, default=list)


class MemoryRelation(Base):
    __tablename__ = "t_memory_relations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "from_memory_id"],
            ["t_memories.workspace_id", "t_memories.id"],
            name="fk_relation_from",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "to_memory_id"],
            ["t_memories.workspace_id", "t_memories.id"],
            name="fk_relation_to",
            ondelete="CASCADE",
        ),
        UniqueConstraint("from_memory_id", "to_memory_id", "relation_type", name="uq_memory_relation"),
        CheckConstraint("from_memory_id <> to_memory_id", name="ck_memory_relation_self"),
        Index("ix_relation_target", "to_memory_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    from_memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    to_memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    relation_type: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_users.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryEvent(Identity, Base):
    __tablename__ = "t_memory_events"
    __table_args__ = (
        memory_fk("fk_event_memory"),
        Index("ix_memory_event_agent", "agent_id", "created_at", "id"),
        Index("ix_memory_event_record", "memory_id", "created_at", "id"),
        Index(
            "uq_memory_event_idempotency",
            "agent_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )
    event_type: Mapped[str] = mapped_column(String(40))
    actor_type: Mapped[str] = mapped_column(String(32), default="system")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_users.id", ondelete="SET NULL")
    )
    actor_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id", ondelete="SET NULL")
    )
    operation_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    before_revision: Mapped[int | None] = mapped_column(Integer)
    after_revision: Mapped[int | None] = mapped_column(Integer)
    data_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class MemoryIssue(Identity, Base):
    __tablename__ = "t_memory_issues"
    __table_args__ = (
        memory_fk("fk_issue_memory"),
        Index("ix_memory_issue_queue", "agent_id", "status", "severity", "updated_at", "id"),
        Index(
            "uq_memory_issue_open",
            "agent_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('open', 'deferred')"),
        ),
    )
    issue_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    status: Mapped[str] = mapped_column(String(16), default="open")
    dedupe_key: Mapped[str] = mapped_column(String(255))
    related_memory_ids: Mapped[list] = mapped_column(JSONB, default=list)
    reason_code: Mapped[str] = mapped_column(String(80))
    detail_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_users.id", ondelete="SET NULL")
    )
    resolution_json: Mapped[dict] = mapped_column(JSONB, default=dict)
