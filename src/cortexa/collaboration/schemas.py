"""Agent Collaboration 数据结构定义"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentHandoff(BaseModel):
    """Agent 协作请求 - 主 Agent 生成的结构化 Handoff"""
    source_agent_id: str
    target_agent_id: str
    task: str
    background_context: dict[str, Any] = Field(default_factory=dict)
    include_history: bool = True
    known_facts: list[str] = Field(default_factory=list)
    question: str
    constraints: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    reference_materials: list[str] = Field(default_factory=list)
    web_context: dict[str, str] | None = None
    supplemental_prompt: str | None = None
    dependency_results: list[dict[str, Any]] = Field(default_factory=list)
    resolver_context: dict[str, Any] = Field(default_factory=dict, exclude=True)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)


class AgentHandoffResult(BaseModel):
    """Agent 协作结果 - 目标 Agent 返回的结构化结果"""
    status: str = "success"  # success | failed | timeout
    summary: str = ""
    result: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float | None = None
    completed_at: str = ""
    duration_ms: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)


class AgentCollaborationRecord(BaseModel):
    """协作记录 - 用于 API 返回"""
    id: str
    conversation_id: str
    source_agent_id: str
    source_agent_name: str = ""
    target_agent_id: str
    target_agent_name: str = ""
    task: str
    question: str
    status: str
    result_summary: str | None = None
    result_content: str | None = None
    confidence: float | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    call_depth: int = 1
    started_at: str | None = None
    completed_at: str | None = None

    model_config = {"from_attributes": True}


class CollaborationLimits(BaseModel):
    """协作限制配置"""
    max_agents_per_request: int = 3
    max_call_depth: int = 2
    timeout_seconds: int = 120


# 默认限制
DEFAULT_LIMITS = CollaborationLimits()
