"""Meeting module database models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .engine import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    """AI 会议 — 核心表"""
    __tablename__ = "t_meetings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False, comment="会议议题")
    purpose: Mapped[str] = mapped_column(
        String(32), default="analysis",
        comment="decision/solution/risk_assessment/problem_solving/analysis/custom"
    )
    host_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True,
        comment="主持人 Agent"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="preparing",
        comment="preparing/running/completed/failed/cancelled"
    )
    max_rounds: Mapped[int] = mapped_column(Integer, default=3, comment="最大讨论轮次")
    current_round: Mapped[int] = mapped_column(Integer, default=0, comment="当前轮次")
    config: Mapped[dict] = mapped_column(JSON, default=dict, comment="会议配置")
    attachments: Mapped[list] = mapped_column(JSON, default=list, comment="附件列表 [{name, path, size, type}]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow)

    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    rounds: Mapped[list["MeetingRound"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    messages: Mapped[list["MeetingMessage"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    conclusion: Mapped["MeetingConclusion | None"] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan"
    )
    todos: Mapped[list["TodoItem"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class MeetingParticipant(Base):
    """会议参与者"""
    __tablename__ = "t_meeting_participants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_meetings.id", ondelete="CASCADE"), nullable=False
    )
    participant_type: Mapped[str] = mapped_column(
        String(16), default="agent", comment="agent/human"
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="角色描述")
    is_host: Mapped[bool] = mapped_column(default=False, comment="是否主持人")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")


class MeetingRound(Base):
    """讨论轮次"""
    __tablename__ = "t_meeting_rounds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_meetings.id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True, comment="本轮讨论主题")
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="pending/running/completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped["Meeting"] = relationship(back_populates="rounds")


class MeetingMessage(Base):
    """会议消息 — 讨论记录"""
    __tablename__ = "t_meeting_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_meetings.id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sender_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="agent/host/system"
    )
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(32), default="analysis",
        comment="analysis/summary/question/response/conclusion/system"
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped["Meeting"] = relationship(back_populates="messages")


class MeetingConclusion(Base):
    """会议结论"""
    __tablename__ = "t_meeting_conclusions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_meetings.id", ondelete="CASCADE"), nullable=False,
        unique=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, comment="结论摘要")
    key_decisions: Mapped[list] = mapped_column(JSON, default=list, comment="关键决策列表")
    disagreements: Mapped[list] = mapped_column(JSON, default=list, comment="未达成一致的分歧")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped["Meeting"] = relationship(back_populates="conclusion")


class TodoItem(Base):
    """待办事项"""
    __tablename__ = "t_todo_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_meetings.id", ondelete="SET NULL"), nullable=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_type: Mapped[str] = mapped_column(
        String(16), default="agent", comment="agent/human"
    )
    assignee_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    assignee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[str] = mapped_column(
        String(16), default="medium", comment="high/medium/low"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", comment="pending/in_progress/completed/cancelled"
    )
    due_date: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="截止日期 YYYY-MM-DD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped["Meeting | None"] = relationship(back_populates="todos")
