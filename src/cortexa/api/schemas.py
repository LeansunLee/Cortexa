"""Pydantic schemas for API request/response."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from cortexa.collaboration.drafts import CollaborationDraft
from cortexa.runtime.collaboration import CollaborationSettings


# -- Workspace -------------------------------------------------------------
class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None
    default_model_provider: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_model_provider: str | None = None
    system_prompt: str | None = None


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    default_model_provider: str | None
    system_prompt: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Agent -----------------------------------------------------------------
class AgentCreate(BaseModel):
    collaboration: CollaborationSettings = Field(default_factory=CollaborationSettings)
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
    web_search_enabled: bool = False


class AgentUpdate(BaseModel):
    collaboration: CollaborationSettings | None = None
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
    web_search_enabled: bool | None = None
    status: str | None = None


class AgentOut(BaseModel):
    collaboration: dict[str, Any] | None = None
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
    web_search_enabled: bool = False
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


class ProxyInputResolutionRequest(BaseModel):
    task: str = ""
    explicit_input: dict[str, Any] = Field(default_factory=dict)
    conversation_context: Any = Field(default_factory=list)
    system: dict[str, Any] = Field(default_factory=dict)
    previous_agent_output: Any = Field(default_factory=list)
    input_schema: dict[str, Any] | None = None
    proxy_config: dict[str, Any] | None = None


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


class KnowledgeBaseStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]


class NameUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class KnowledgeBaseDescriptionUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)


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
    collaboration_drafts: list[CollaborationDraft] | None = Field(default=None, max_length=3)
    content: str
    attachments: list[dict] | None = None


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
    name: str = Field(max_length=200)
    content: str = Field(min_length=1, max_length=1_000_000)
    folder_id: uuid.UUID | None = None


class DocumentContentUpdate(BaseModel):
    """Full-text save for editable plain-text documents."""

    content: str = Field(min_length=1, max_length=1_000_000)


class DocumentOut(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    name: str
    content: str | None
    status: str
    valid_until: date | None = None
    folder_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# -- KnowledgeBaseDetail ---------------------------------------------------
class KnowledgeFolderOut(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str

    model_config = {"from_attributes": True}


class KnowledgeBaseDetailOut(KnowledgeBaseOut):
    documents: list[DocumentOut] = []
    folders: list[KnowledgeFolderOut] = []


class DocumentValidityUpdate(BaseModel):
    valid_until: date | None = None


class DocumentSummaryUpdate(BaseModel):
    """Manual override of the retrieval summary stored in Document.content."""

    content: str = Field(min_length=1, max_length=8000)

# -- DataSource --------------------------------------------------------------
class DataSourceCreate(BaseModel):
    name: str
    description: str | None = None
    type: str  # postgres, mysql, api
    config: dict = {}  # host, port, database, etc.
    credential_id: str | None = None


class DataSourceOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    type: str
    status: str
    credential_id: uuid.UUID | None
    config: dict
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# -- DataCredential ----------------------------------------------------------
class DataCredentialCreate(BaseModel):
    name: str
    type: str  # password, token, api_key
    data: dict  # {username, password} or {token} or {api_key}


class DataCredentialOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    type: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# -- DataSchema --------------------------------------------------------------
class DataSchemaOut(BaseModel):
    id: uuid.UUID
    data_source_id: uuid.UUID
    schema_name: str
    table_name: str
    column_name: str | None
    data_type: str | None
    description: str | None
    is_queryable: bool
    is_sensitive: bool
    model_config = {"from_attributes": True}


# -- DataCapability ----------------------------------------------------------
class DataCapabilityCreate(BaseModel):
    name: str
    description: str | None = None
    data_source_id: str
    type: str = "predefined_query"
    input_schema: dict = {}
    output_schema: dict = {}
    query_template: str | None = None
    original_sql: str | None = None
    allowed_tables: list[str] = []
    allowed_columns: list[str] = []
    row_limit: int = 1000
    timeout_seconds: int = 30


class DataCapabilityStatusUpdate(BaseModel):
    status: Literal["active", "inactive"]


class DataCapabilityOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    data_source_id: uuid.UUID
    type: str
    input_schema: dict
    output_schema: dict
    query_template: str | None
    original_sql: str | None
    allowed_tables: list
    allowed_columns: list
    row_limit: int
    timeout_seconds: int
    status: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# -- AgentDataBinding -------------------------------------------------------
class AgentDataBindingCreate(BaseModel):
    agent_id: str
    data_capability_id: str


class AgentDataBindingOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    data_capability_id: uuid.UUID
    created_at: datetime
    model_config = {"from_attributes": True}


# -- DataQuery ---------------------------------------------------------------
class DataQueryCreate(BaseModel):
    data_capability_id: str
    params: dict = {}
    source: str = "manual"


class DataQueryOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None
    data_capability_id: uuid.UUID | None
    data_source_id: uuid.UUID | None
    query_text: str | None
    input_params: dict | None
    output_result: dict | None
    status: str
    duration_ms: int | None
    error_message: str | None
    source: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


# -- Update Schemas ----------------------------------------------------------
class DataSourceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = None
    config: dict | None = None
    credential_id: str | None = None


class DataCredentialUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    data: dict | None = None
