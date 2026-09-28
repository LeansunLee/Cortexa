"""Additive audit tables; no business-content or credential storage."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cortexa.db.engine import Base


class UsageOperation(Base):
    __tablename__ = "t_llm_usage_operations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    trigger: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[str | None] = mapped_column(String(80), index=True)
    user_name: Mapped[str | None] = mapped_column(String(160))
    workspace_id: Mapped[str | None] = mapped_column(String(80), index=True)
    object_type: Mapped[str | None] = mapped_column(String(80))
    object_id: Mapped[str | None] = mapped_column(String(100))


class UsageCall(Base):
    __tablename__ = "t_llm_usage_calls"
    __table_args__ = (
        Index("ix_usage_model_time", "provider", "requested_model", "started_at"),
        Index("ix_usage_action_time", "action", "started_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_llm_usage_operations.id"), index=True)
    step_id: Mapped[str] = mapped_column(String(80))
    parent_step_id: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(String(80))
    trigger: Mapped[str] = mapped_column(String(40))
    agent_id: Mapped[str | None] = mapped_column(String(80), index=True)
    agent_name: Mapped[str | None] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(160))
    provider_kind: Mapped[str] = mapped_column(String(40))
    requested_model: Mapped[str] = mapped_column(String(200))
    actual_model: Mapped[str | None] = mapped_column(String(200))
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), index=True)
    usage_status: Mapped[str] = mapped_column(String(30), index=True)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_creation_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    retry_count: Mapped[int] = mapped_column(default=0)
    error_type: Mapped[str | None] = mapped_column(String(100))
    usage_detail: Mapped[dict] = mapped_column(JSON, default=dict)
