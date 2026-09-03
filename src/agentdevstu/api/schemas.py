"""Pydantic schemas for API request/response."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# -- Workspace -------------------------------------------------------------
class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None
    default_model_provider: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_model_provider: str | None = None


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    default_model_provider: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Agent -----------------------------------------------------------------
class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    avatar: str | None = None
    agent_type: str = "llm"
    proxy_config: dict[str, Any] = Field(default_factory=dict)
    role: str | None = None
    personality: str | None = None
    responsibilities: str | None = None
    boundaries: str | None = None
    behavior: str | None = None
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 4096
    system_prompt: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[uuid.UUID] = Field(default_factory=list)
    tool_ids: list[uuid.UUID] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    avatar: str | None = None
    agent_type: str | None = None
    proxy_config: dict[str, Any] | None = None
    role: str | None = None
    personality: str | None = None
    responsibilities: str | None = None
    boundaries: str | None = None
    behavior: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    tags: list[str] | None = None
    knowledge_base_ids: list[uuid.UUID] | None = None
    tool_ids: list[uuid.UUID] | None = None
    status: str | None = None


class AgentOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    avatar: str | None
    agent_type: str
    proxy_config: dict[str, Any]
    role: str | None
    personality: str | None
    responsibilities: str | None
    boundaries: str | None
    behavior: str | None
    model: str | None
    temperature: float
    max_tokens: int
    system_prompt: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: str
    current_version: int
    tags: list[str]
    knowledge_base_ids: list[uuid.UUID]
    tool_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- AgentVersion ----------------------------------------------------------
class AgentVersionCreate(BaseModel):
    release_notes: str | None = None


class AgentVersionOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    version_number: int
    snapshot: dict[str, Any]
    is_current: bool
    is_published: bool
    published_at: datetime | None
    release_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- AgentRun --------------------------------------------------------------
class AgentRunCreate(BaseModel):
    input_data: dict[str, Any]


class AgentRunOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    status: str
    error_message: str | None
    tokens_used: int
    duration_ms: int
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


# -- Agent Test ------------------------------------------------------------
class AgentTestRequest(BaseModel):
    input_data: dict[str, Any]
    version_id: uuid.UUID | None = None


class AgentTestResponse(BaseModel):
    success: bool
    output_data: dict[str, Any] | None = None
    error: str | None = None
    tokens_used: int = 0
    duration_ms: int = 0


# -- Agent Publish ---------------------------------------------------------
class AgentPublishRequest(BaseModel):
    release_notes: str | None = None


class AgentPublishResponse(BaseModel):
    success: bool
    version_number: int | None = None
    errors: list[str] = Field(default_factory=list)


# -- KnowledgeBase ---------------------------------------------------------
class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str | None = None
    type: str = "documents"
    agent_id: str | None = None  # None = 空间知识库, 有值 = Agent 独立知识库


class KnowledgeBaseOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    name: str
    description: str | None
    type: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Tool ------------------------------------------------------------------
class ToolCreate(BaseModel):
    name: str
    description: str | None = None
    type: str = "function"
    config: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ToolOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    type: str
    config: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Workflow --------------------------------------------------------------
class WorkflowCreate(BaseModel):
    name: str
    description: str | None = None


class WorkflowOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    status: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Task ------------------------------------------------------------------
class TaskCreate(BaseModel):
    name: str
    description: str | None = None
    agent_id: uuid.UUID | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)


class TaskOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    status: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Conversation ----------------------------------------------------------
class ConversationCreate(BaseModel):
    agent_id: uuid.UUID | None = None
    title: str | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None = None
    agent_avatar: str | None = None
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationMessageCreate(BaseModel):
    content: str


class ConversationMessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


# -- Model Provider -------------------------------------------------------
class ModelProviderItem(BaseModel):
    name: str
    kind: str
    model: str
    display_name: str | None = None


class ModelProviderListOut(BaseModel):
    providers: list[ModelProviderItem]
    default_provider: str | None = None

# -- Document --------------------------------------------------------------
class DocumentCreate(BaseModel):
    name: str
    content: str


class DocumentOut(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    name: str
    content: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# -- KnowledgeBaseDetail ---------------------------------------------------
class KnowledgeBaseDetailOut(KnowledgeBaseOut):
    documents: list[DocumentOut] = []
