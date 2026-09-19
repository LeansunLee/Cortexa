"""
SQLAlchemy 数据库模型定义

本模块定义了 AgentDevStu 平台的所有数据库表结构。
所有表名以 "t_" 前缀命名，便于识别和管理。

表结构概览：
- t_workspaces: 工作空间，是系统的核心组织单元
- t_agents: 智能体，定义 AI 数字员工的配置
- t_agent_versions: 智能体版本，保存配置的不可变快照
- t_agent_runs: 智能体运行记录，追踪每次执行
- t_knowledge_bases: 知识库，管理文档和知识
- t_documents: 文档，知识库中的具体文档
- t_rules: 规则库，定义行为约束和边界
- t_tools: 工具，可被智能体调用的外部工具
- t_workflows: 工作流，定义多智能体协作流程
- t_workflow_nodes: 工作流节点，工作流中的单个步骤
- t_workflow_edges: 工作流边，节点之间的连接关系
- t_tasks: 任务，需要执行的具体工作
- t_task_runs: 任务运行记录，追踪任务执行过程
- t_conversations: 对话，用户与智能体的会话
- t_conversation_messages: 对话消息，会话中的单条消息
- t_memories: 记忆，智能体的短期/长期记忆
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
    ForeignKeyConstraint,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .engine import Base


def _uuid() -> uuid.UUID:
    """生成 UUID 主键"""
    return uuid.uuid4()


def _utcnow() -> datetime:
    """获取当前 UTC 时间"""
    return datetime.now(timezone.utc)


# =============================================================================
# 工作空间 (Workspace)
# =============================================================================
class Workspace(Base):
    """
    工作空间表 - 系统的核心组织单元
    """
    __table_args__ = {'comment': '工作空间表 - 系统的核心组织单元，是 Agent、知识库、工具、工作流等资源的容器'}
    """
    工作空间表 - 系统的核心组织单元

    工作空间是 Agent、知识库、工具、工作流等资源的容器。
    每个用户可以创建多个工作空间，每个工作空间独立管理其资源。

    使用场景：
    - 团队按项目创建工作空间
    - 不同业务线使用不同工作空间
    - 资源隔离和权限控制
    """
    __tablename__ = "t_workspaces"

    # 主键
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="工作空间唯一标识符"
    )

    # 基础信息
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="工作空间名称，例如：'产品研发团队'"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="工作空间描述，说明用途和目标"
    )
    default_model_provider: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="默认模型供应商名称，从 config.yaml 的 llm.providers 中选择"
    )
    system_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="工作空间系统提示词，注入到该空间内所有 Agent 的 prompt 中"
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active(活跃), archived(已归档)"
    )
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    # 关系：一个工作空间包含多个智能体
    agents: Mapped[list["Agent"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：一个工作空间包含多个知识库
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：一个工作空间包含多个规则
    rules: Mapped[list["Rule"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：一个工作空间包含多个工具
    tools: Mapped[list["Tool"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：一个工作空间包含多个工作流
    workflows: Mapped[list["Workflow"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：一个工作空间包含多个任务
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：一个工作空间包含多个对话
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：一个工作空间包含多个记忆
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    # 关系：数据源
    data_sources: Mapped[list["DataSource"]] = relationship(
        primaryjoin="Workspace.id == DataSource.workspace_id",
        back_populates="data_source_workspace", cascade="all, delete-orphan"
    )
    # 关系：数据能力
    data_capabilities: Mapped[list["DataCapability"]] = relationship(
        primaryjoin="Workspace.id == DataCapability.workspace_id",
        back_populates="capability_workspace", cascade="all, delete-orphan"
    )


# =============================================================================
# 智能体 (Agent)
# =============================================================================
class Agent(Base):
    """
    智能体表 - AI 数字员工的核心配置
    """
    __table_args__ = (UniqueConstraint('workspace_id', 'id', name='uq_agent_workspace_id'), {'comment': '智能体表 - AI 数字员工的核心配置'})
    """
    智能体表 - AI 数字员工的核心配置

    智能体是一个具有明确角色、职责、能力边界的 AI 实体。
    它可以被 Workflow 调度，可以调用 Knowledge 和 Tool，
    具有标准的输入输出接口。

    核心概念：
    - Persona (人格): 智能体的性格特征
    - Role (职责): 智能体负责的工作
    - Boundary (边界): 智能体能做什么，不能做什么
    - Behavior (行为): 智能体的工作方式
    - Schema (接口): 标准化的输入输出格式

    生命周期：
    创建 → 配置 → 保存草稿 → 测试 → 创建版本 → 发布 → 对话/被调用
    """
    __tablename__ = "t_agents"

    # 主键
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="智能体唯一标识符"
    )

    # 所属工作空间
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID，外键关联 t_workspaces"
    )

    # ========== 基础信息 ==========
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="智能体名称，例如：'资深产品经理'"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="智能体功能描述"
    )
    avatar: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="头像 URL 或 emoji"
    )

    # ========== Persona 人格 ==========
    personality: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="人格特征描述，例如：'严谨、理性、主动、专业'"
    )

    # ========== Role 职责 ==========
    role: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="角色名称，例如：'产品经理'"
    )
    responsibilities: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="职责描述，列出主要负责的工作"
    )

    # ========== Boundary 工作边界 ==========
    boundaries: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="工作边界，明确可以做什么、不可以做什么"
    )

    # ========== Behavior 工作方式 ==========
    behavior: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="工作方式描述，定义工作流程和方法"
    )

    # ========== Knowledge 知识绑定 ==========
    knowledge_base_ids: Mapped[list] = mapped_column(
        JSON, default=list,
        comment="绑定的知识库 ID 列表，例如：['uuid1', 'uuid2']"
    )

    # ========== Tools 工具绑定 ==========
    tool_ids: Mapped[list] = mapped_column(
        JSON, default=list,
        comment="绑定的工具 ID 列表，例如：['uuid1', 'uuid2']"
    )

    @property
    def web_search_enabled(self) -> bool:
        from agentdevstu.tools.web_search import search_enabled
        return search_enabled(self)

    # ========== Memory 记忆配置 ==========
    memory_config: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="记忆配置，例如：{'type': 'short_term', 'max_items': 100}"
    )

    # ========== Collaboration 协作配置 ==========
    collaboration: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="协作配置，定义与其他智能体的协作方式"
    )

    # ========== Quality Policy 质量策略 ==========
    quality_policy: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="质量策略，定义输出质量要求和检查规则"
    )

    # ========== Permission 权限 ==========
    permissions: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="权限配置，控制智能体可访问的资源"
    )

    # ========== Agent Type 智能体类型 ==========
    agent_type: Mapped[str] = mapped_column(
        String(32), default="llm",
        comment="智能体类型：llm(AI推理), proxy(代理外部系统)"
    )

    # ========== Proxy Config 代理配置 ==========
    proxy_config: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="代理配置，仅 proxy 类型使用：endpoint, method, headers, auth, timeout_ms 等"
    )

    # ========== Model Config 模型配置 ==========
    model: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="使用的模型名称，例如：'gpt-4', 'deepseek-chat'"
    )
    temperature: Mapped[float] = mapped_column(
        Float, default=0.2,
        comment="温度参数，控制输出的随机性，范围 0-2"
    )
    max_tokens: Mapped[int] = mapped_column(
        Integer, default=4096,
        comment="最大 token 数量，限制输出长度"
    )
    system_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="系统提示词，可选，会从配置自动生成"
    )

    # ========== Input/Output Schema 接口定义 ==========
    input_schema: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输入 Schema (JSON Schema 格式)，定义接受的输入参数"
    )
    output_schema: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输出 Schema (JSON Schema 格式)，定义输出的数据结构"
    )

    # ========== 状态和版本 ==========
    status: Mapped[str] = mapped_column(
        String(32), default="draft",
        comment="状态：draft(草稿), active(已发布), disabled(已禁用), archived(已归档)"
    )
    current_version: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="当前版本号，0 表示未发布过"
    )

    # ========== 标签 ==========
    tags: Mapped[list] = mapped_column(
        JSON, default=list,
        comment="标签列表，用于分类和筛选"
    )

    # ========== 时间戳 ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    # ========== 关系 ==========
    workspace: Mapped["Workspace"] = relationship(
        back_populates="agents"
    )
    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="agent"
    )
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="agent", foreign_keys="Memory.agent_id",
        primaryjoin="Agent.id == Memory.agent_id", passive_deletes="all",
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="agent"
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    # 关系：数据能力绑定
    data_bindings: Mapped[list["AgentDataBinding"]] = relationship(
        primaryjoin="Agent.id == AgentDataBinding.agent_id",
        back_populates="agent_binding", cascade="all, delete-orphan"
    )
    data_bindings: Mapped[list["AgentDataBinding"]] = relationship(
        primaryjoin="Agent.id == AgentDataBinding.agent_id",
        back_populates="agent_binding", cascade="all, delete-orphan"
    )


# =============================================================================
# 智能体版本 (AgentVersion)
# =============================================================================
class AgentVersion(Base):
    """
    智能体版本表 - 保存配置的不可变快照
    """
    __table_args__ = {'comment': '智能体版本表 - 保存配置的不可变快照，用于版本追踪和回滚'}
    """
    智能体版本表 - 保存配置的不可变快照

    每次发布智能体时，会创建一个版本记录，包含当时所有配置的快照。
    版本是不可变的，确保历史可追溯。

    用途：
    - 追踪配置变更历史
    - 支持回滚到历史版本
    - 运行时使用特定版本的配置
    - 审计和合规
    """
    __tablename__ = "t_agent_versions"

    # 主键
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="版本记录唯一标识符"
    )

    # 关联的智能体
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=False,
        comment="所属智能体 ID，外键关联 t_agents"
    )

    # 版本信息
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="版本号，从 1 开始递增"
    )

    # 版本快照 - 包含 Agent 所有配置的不可变副本
    snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment="配置快照，包含 name, role, personality, model 等所有字段"
    )

    # 版本状态
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="是否为当前版本"
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="是否已发布"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="发布时间"
    )

    # 发布说明
    release_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="版本说明，描述本次更新的内容"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    # 关系
    agent: Mapped["Agent"] = relationship(
        back_populates="versions"
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="agent_version"
    )


# =============================================================================
# 智能体运行记录 (AgentRun)
# =============================================================================
class AgentRun(Base):
    """
    智能体运行记录表 - 追踪每次执行
    """
    __table_args__ = {'comment': '智能体运行记录表 - 追踪智能体的每次执行，包括输入、输出、状态、耗时'}
    """
    智能体运行记录表 - 追踪每次执行

    记录智能体的每次运行，包括输入、输出、状态、耗时等。
    用于性能分析、问题排查、质量监控。
    """
    __tablename__ = "t_agent_runs"

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id"), nullable=True, index=True)

    # 主键
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="运行记录唯一标识符"
    )

    # 关联信息
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=False,
        comment="执行的智能体 ID"
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agent_versions.id"), nullable=False,
        comment="使用的版本 ID"
    )

    # 输入输出
    input_data: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment="输入数据，符合 input_schema"
    )
    output_data: Mapped[dict] = mapped_column(
        JSON, nullable=True,
        comment="输出数据，符合 output_schema"
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(32), default="running",
        comment="状态：running(运行中), completed(已完成), failed(失败)"
    )

    # 错误信息
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="错误信息"
    )
    error_traceback: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="错误堆栈，用于调试"
    )

    # 性能指标
    tokens_used: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="消耗的 token 数量"
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="执行耗时（毫秒）"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="开始执行时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="完成时间"
    )

    # 关系
    agent: Mapped["Agent"] = relationship(
        back_populates="runs"
    )
    agent_version: Mapped["AgentVersion"] = relationship(
        back_populates="runs"
    )


# =============================================================================
# 知识库 (KnowledgeBase)
# =============================================================================
class KnowledgeBase(Base):
    """
    知识库表 - 管理文档和知识
    """
    __table_args__ = {'comment': '知识库表 - 管理文档和知识，是智能体可以检索和使用的知识来源'}
    """
    知识库表 - 管理文档和知识

    知识库是智能体可以检索和使用的知识来源。
    支持文档、FAQ、网页等多种类型。
    """
    __tablename__ = "t_knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="知识库唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True,
        comment="所属 Agent ID，为空表示空间知识库，有值表示 Agent 独立知识库"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="知识库名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="知识库描述"
    )
    type: Mapped[str] = mapped_column(
        String(32), default="documents",
        comment="类型：documents(文档), faq(问答), web(网页)"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active(活跃), indexing(索引中), error(错误)"
    )
    config: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="配置信息，如分块策略、嵌入模型等"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="knowledge_bases"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    folders: Mapped[list["KnowledgeFolder"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        cascade="all, delete-orphan"
    )


class KnowledgeFolder(Base):
    """知识库目录，只用于用户分类管理，不参与检索。"""
    __tablename__ = "t_knowledge_folders"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "parent_id", "name", name="uq_kb_folder_sibling_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("t_knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_knowledge_folders.id", ondelete="RESTRICT"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow)

    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="folders")
    parent: Mapped["KnowledgeFolder | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["KnowledgeFolder"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="folder")


# =============================================================================
# 文档 (Document)
# =============================================================================
class Document(Base):
    """
    文档表 - 知识库中的具体文档
    """
    __table_args__ = {'comment': '文档表 - 知识库中的具体文档，存储文档内容和元数据'}
    """
    文档表 - 知识库中的具体文档

    存储知识库中的文档内容和元数据。
    """
    __tablename__ = "t_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="文档唯一标识符"
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_knowledge_bases.id"), nullable=False,
        comment="所属知识库 ID"
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_knowledge_folders.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="所属文件夹，NULL 表示知识库根目录"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_users.id"), nullable=True, index=True,
        comment="上传或创建文档的用户，历史文档可能为空"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="文档名称"
    )
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="文档内容"
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="元数据，如来源、作者、标签等"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active(活跃), archived(已归档)"
    )
    valid_until: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        comment="有效期截止日期（含当天），NULL 表示永久有效"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        back_populates="documents"
    )
    folder: Mapped["KnowledgeFolder | None"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# =============================================================================
# 文档分块 (DocumentChunk) - RAG 向量检索
# =============================================================================
class DocumentChunk(Base):
    """
    文档分块表 - 存储文档的分块内容和向量嵌入，用于 RAG 语义检索
    """
    __table_args__ = {'comment': '文档分块表 - 存储文档的分块内容和向量嵌入，用于 RAG 语义检索'}
    __tablename__ = "t_document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="分块唯一标识符"
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_documents.id", ondelete="CASCADE"), nullable=False,
        comment="所属文档 ID"
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_knowledge_bases.id"), nullable=False,
        comment="所属知识库 ID，冗余存储便于检索"
    )
    chunk_index: Mapped[int] = mapped_column(
        nullable=False,
        comment="分块序号，从 0 开始"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="分块文本内容"
    )
    token_count: Mapped[int] = mapped_column(
        nullable=False, default=0,
        comment="分块的 token 数量"
    )
    embedding: Mapped[bytes | None] = mapped_column(
        nullable=True,
        comment="向量嵌入（1536维 float32，二进制存储）"
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="元数据，如页码、章节等"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )

    document: Mapped["Document"] = relationship(
        back_populates="chunks"
    )


# =============================================================================
# 规则 (Rule)
# =============================================================================
class Rule(Base):
    """
    规则表 - 定义行为约束和边界
    """
    __table_args__ = {'comment': '规则表 - 定义行为约束和边界，用于约束智能体的行为'}
    """
    规则表 - 定义行为约束和边界

    规则用于约束智能体的行为，确保输出符合要求。
    """
    __tablename__ = "t_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="规则唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="规则名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="规则描述"
    )
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="规则内容"
    )
    type: Mapped[str] = mapped_column(
        String(32), default="guardrail",
        comment="类型：guardrail(护栏), quality(质量), safety(安全)"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active(启用), disabled(禁用)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="rules"
    )


# =============================================================================
# 工具 (Tool)
# =============================================================================
class Tool(Base):
    """
    工具表 - 可被智能体调用的外部工具
    """
    __table_args__ = {'comment': '工具表 - 可被智能体调用的外部工具，如搜索、数据库查询、API调用'}
    """
    工具表 - 可被智能体调用的外部工具

    工具是智能体与外部系统交互的接口。
    例如：搜索工具、数据库查询、API 调用等。
    """
    __tablename__ = "t_tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="工具唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="工具名称，例如：'web_search'"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="工具功能描述"
    )
    type: Mapped[str] = mapped_column(
        String(32), default="function",
        comment="类型：function(函数), api(API), plugin(插件)"
    )
    config: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="工具配置，如 API 地址、认证信息等"
    )
    input_schema: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输入参数 Schema"
    )
    output_schema: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输出结果 Schema"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active(可用), disabled(禁用)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="tools"
    )


# =============================================================================
# 工作流 (Workflow)
# =============================================================================
class Workflow(Base):
    """
    工作流表 - 定义多智能体协作流程
    """
    __table_args__ = {'comment': '工作流表 - 定义多智能体协作流程，包含节点和边'}
    """
    工作流表 - 定义多智能体协作流程

    工作流定义了多个智能体如何协同完成任务。
    包含节点（步骤）和边（连接关系）。
    """
    __tablename__ = "t_workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="工作流唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="工作流名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="工作流描述"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft",
        comment="状态：draft(草稿), active(已发布), disabled(已禁用)"
    )
    config: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="工作流配置，如超时时间、重试策略等"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="workflows"
    )
    nodes: Mapped[list["WorkflowNode"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    edges: Mapped[list["WorkflowEdge"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    runs: Mapped[list["TaskRun"]] = relationship(
        back_populates="workflow"
    )


# =============================================================================
# 工作流节点 (WorkflowNode)
# =============================================================================
class WorkflowNode(Base):
    """
    工作流节点表 - 工作流中的单个步骤
    """
    __table_args__ = {'comment': '工作流节点表 - 工作流中的单个步骤，通常对应一个智能体或处理逻辑'}
    """
    工作流节点表 - 工作流中的单个步骤

    每个节点通常对应一个智能体或处理逻辑。
    """
    __tablename__ = "t_workflow_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="节点唯一标识符"
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workflows.id"), nullable=False,
        comment="所属工作流 ID"
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True,
        comment="关联的智能体 ID（如果是智能体节点）"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="节点名称"
    )
    type: Mapped[str] = mapped_column(
        String(32), default="agent",
        comment="类型：agent(智能体), condition(条件), transform(转换)"
    )
    config: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="节点配置"
    )
    position_x: Mapped[float] = mapped_column(
        Float, default=0,
        comment="画布 X 坐标（用于可视化编辑）"
    )
    position_y: Mapped[float] = mapped_column(
        Float, default=0,
        comment="画布 Y 坐标（用于可视化编辑）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )

    workflow: Mapped["Workflow"] = relationship(
        back_populates="nodes"
    )


# =============================================================================
# 工作流边 (WorkflowEdge)
# =============================================================================
class WorkflowEdge(Base):
    """
    工作流边表 - 节点之间的连接关系
    """
    __table_args__ = {'comment': '工作流边表 - 节点之间的连接关系，定义数据如何流动'}
    """
    工作流边表 - 节点之间的连接关系

    定义数据如何在节点之间流动。
    """
    __tablename__ = "t_workflow_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="边唯一标识符"
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workflows.id"), nullable=False,
        comment="所属工作流 ID"
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
        comment="源节点 ID"
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
        comment="目标节点 ID"
    )
    source_output: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="源节点的输出字段名"
    )
    target_input: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="目标节点的输入字段名"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )

    workflow: Mapped["Workflow"] = relationship(
        back_populates="edges"
    )


# =============================================================================
# 任务 (Task)
# =============================================================================
class Task(Base):
    """
    任务表 - 需要执行的具体工作
    """
    __table_args__ = {'comment': '任务表 - 需要执行的具体工作，是对智能体的具体调用请求'}
    """
    任务表 - 需要执行的具体工作

    任务是对智能体的具体调用请求。
    """
    __tablename__ = "t_tasks"

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id"), nullable=True, index=True)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="任务唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True,
        comment="执行的智能体 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="任务名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="任务描述"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending",
        comment="状态：pending(待处理), running(运行中), completed(已完成), failed(失败)"
    )
    input_data: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输入数据"
    )
    output_data: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输出结果"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="tasks"
    )
    agent: Mapped["Agent"] = relationship(
        back_populates="tasks"
    )
    runs: Mapped[list["TaskRun"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


# =============================================================================
# 任务运行记录 (TaskRun)
# =============================================================================
class TaskRun(Base):
    """
    任务运行记录表 - 追踪任务执行过程
    """
    __table_args__ = {'comment': '任务运行记录表 - 追踪任务的每次执行，包括工作流执行'}
    """
    任务运行记录表 - 追踪任务执行过程

    记录任务的每次执行，包括工作流执行。
    """
    __tablename__ = "t_task_runs"

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id"), nullable=True, index=True)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="运行记录唯一标识符"
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_tasks.id"), nullable=False,
        comment="所属任务 ID"
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workflows.id"), nullable=True,
        comment="执行的工作流 ID（如果是工作流任务）"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="running",
        comment="状态：running(运行中), completed(已完成), failed(失败)"
    )
    input_data: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输入数据"
    )
    output_data: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输出结果"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="错误信息"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="开始时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="完成时间"
    )

    task: Mapped["Task"] = relationship(
        back_populates="runs"
    )
    workflow: Mapped["Workflow"] = relationship(
        back_populates="runs"
    )


# =============================================================================
# 对话 (Conversation)
# =============================================================================
class Conversation(Base):
    """
    对话表 - 用户与智能体的会话
    """
    __table_args__ = {'comment': '对话表 - 用户与智能体的会话，记录对话的基本信息和状态'}
    """
    对话表 - 用户与智能体的会话

    记录对话的基本信息和状态。
    """
    __tablename__ = "t_conversations"

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id"), nullable=True, index=True)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="对话唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True,
        comment="对话的智能体 ID"
    )
    title: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="对话标题"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active(进行中), archived(已归档)"
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="元数据，如对话摘要、标签等"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="conversations"
    )
    agent: Mapped["Agent"] = relationship(
        back_populates="conversations"
    )
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


# =============================================================================
# 对话消息 (ConversationMessage)
# =============================================================================
class ConversationMessage(Base):
    """
    对话消息表 - 会话中的单条消息
    """
    __table_args__ = {'comment': '对话消息表 - 会话中的单条消息，存储用户输入和智能体回复'}
    """
    对话消息表 - 会话中的单条消息

    存储用户输入和智能体回复。
    """
    __tablename__ = "t_conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="消息唯一标识符"
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_conversations.id"), nullable=False,
        comment="所属对话 ID"
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="角色：user(用户), assistant(助手), system(系统)"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="消息内容"
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="元数据，如 token 数量、模型等"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )

    conversation: Mapped["Conversation"] = relationship(
        back_populates="messages"
    )


# =============================================================================
# 记忆 (Memory)
# =============================================================================
class Memory(Base):
    """Agent-owned cognition. Legacy owner is provenance only, never an ACL."""
    __tablename__ = "t_memories"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "agent_id"], ["t_agents.workspace_id", "t_agents.id"],
                             name="fk_memory_agent_scope", ondelete="RESTRICT"),
        UniqueConstraint("workspace_id", "agent_id", "id", name="uq_memory_scope_id"),
        UniqueConstraint("workspace_id", "id", name="uq_memory_workspace_id"),
        CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memory_importance"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence"),
        CheckConstraint("revision > 0", name="ck_memory_revision"),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from", name="ck_memory_validity"),
        Index("ix_memory_scope_status", "workspace_id", "agent_id", "status", "updated_at", "id"),
        Index("ix_memory_subject", "workspace_id", "agent_id", "subject_type", "subject_id"),
        Index("ix_memory_claim", "workspace_id", "agent_id", "claim_key"),
        Index("ix_memory_hash", "workspace_id", "agent_id", "normalized_hash"),
        Index("ix_memory_valid_from", "workspace_id", "agent_id", "valid_from"),
        Index("ix_memory_valid_to", "workspace_id", "agent_id", "valid_to"),
        Index("ix_memory_occurred", "workspace_id", "agent_id", "occurred_at"),
        Index("ix_memory_expiry", "expires_at"),
        Index("ix_memory_terms", "search_terms", postgresql_using="gin"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("t_workspaces.id"))
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="semantic")
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(default=0.5)
    confidence: Mapped[float] = mapped_column(default=0.5)
    status: Mapped[str] = mapped_column(String(32), default="active")
    source_type: Mapped[str] = mapped_column(String(32), default="conversation")
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    memory_kind: Mapped[str | None] = mapped_column(String(32))
    subject_type: Mapped[str | None] = mapped_column(String(64))
    subject_id: Mapped[str | None] = mapped_column(String(128))
    subject_name: Mapped[str | None] = mapped_column(String(255))
    claim_key: Mapped[str | None] = mapped_column(String(255))
    source_mode: Mapped[str | None] = mapped_column(String(32))
    created_by_type: Mapped[str | None] = mapped_column(String(32))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id", ondelete="SET NULL"))
    created_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_agents.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    risk_level: Mapped[str] = mapped_column(String(16), default="unknown")
    has_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    normalized_hash: Mapped[str | None] = mapped_column(String(64))
    search_terms: Mapped[list] = mapped_column(JSONB, default=list)
    workspace: Mapped["Workspace"] = relationship(back_populates="memories", foreign_keys=[workspace_id])
    agent: Mapped["Agent"] = relationship(back_populates="memories", foreign_keys=[agent_id],
                                          primaryjoin="Agent.id == Memory.agent_id")


# =============================================================================
# 数据源系统 (Data Capability System)
# =============================================================================

class DataSource(Base):
    """数据源表 - 管理外部数据库/API连接"""
    __table_args__ = {'comment': '数据源表 - 管理外部数据库/API连接配置'}
    __tablename__ = "t_data_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="数据源唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="数据源名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="数据源描述"
    )
    type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="类型：postgres, mysql, api"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="inactive",
        comment="状态：active, inactive, error, testing"
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_data_credentials.id"), nullable=True,
        comment="关联凭证 ID"
    )
    config: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="连接配置（非敏感），如 host, port, database"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    data_source_workspace: Mapped["Workspace"] = relationship(
        primaryjoin="DataSource.workspace_id == Workspace.id",
        back_populates="data_sources"
    )
    credential: Mapped["DataCredential | None"] = relationship(
        back_populates="data_sources"
    )
    schemas: Mapped[list["DataSchema"]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )
    capabilities: Mapped[list["DataCapability"]] = relationship(
        back_populates="data_source"
    )


class DataCredential(Base):
    """数据源凭证表 - 加密存储敏感信息"""
    __table_args__ = {'comment': '数据源凭证表 - 加密存储密码/Token/API Key'}
    __tablename__ = "t_data_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="凭证唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="凭证名称"
    )
    type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="凭证类型：password, token, api_key"
    )
    encrypted_data: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="加密后的凭证数据（Fernet加密）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    data_sources: Mapped[list["DataSource"]] = relationship(
        back_populates="credential"
    )


class DataSchema(Base):
    """数据源Schema表 - 表/列元数据"""
    __table_args__ = {'comment': '数据源Schema表 - 同步的表/列元数据信息'}
    __tablename__ = "t_data_schemas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="Schema记录唯一标识符"
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_data_sources.id", ondelete="CASCADE"), nullable=False,
        comment="所属数据源 ID"
    )
    schema_name: Mapped[str] = mapped_column(
        String(255), default="public",
        comment="Schema名称（如 public）"
    )
    table_name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="表名"
    )
    column_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="列名（为空表示表级记录）"
    )
    data_type: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="数据类型"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="字段描述"
    )
    is_queryable: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="是否可查询"
    )
    is_sensitive: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="是否敏感字段"
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="额外元数据"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    data_source: Mapped["DataSource"] = relationship(
        back_populates="schemas"
    )


class DataCapability(Base):
    """数据能力表 - Agent可调用的业务数据能力"""
    __table_args__ = {'comment': '数据能力表 - 定义Agent可调用的业务数据查询能力'}
    __tablename__ = "t_data_capabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="数据能力唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="能力名称，如：查询月度销售额"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="能力描述"
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_data_sources.id"), nullable=False,
        comment="关联数据源 ID"
    )
    type: Mapped[str] = mapped_column(
        String(32), default="predefined_query",
        comment="类型：predefined_query, sql_query, semantic_query（MVP仅支持predefined_query）"
    )
    input_schema: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输入参数 Schema（JSON Schema）"
    )
    output_schema: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="输出结果 Schema（JSON Schema）"
    )
    query_template: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="预定义SQL查询模板，参数用 :param_name 占位"
    )
    original_sql: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="用户录入的原始只读 SQL，保留用于查看、测试和再次 AI 改写"
    )
    allowed_tables: Mapped[list] = mapped_column(
        JSON, default=list,
        comment="允许访问的表名白名单"
    )
    allowed_columns: Mapped[list] = mapped_column(
        JSON, default=list,
        comment="允许访问的列名白名单（空=不限制）"
    )
    row_limit: Mapped[int] = mapped_column(
        Integer, default=1000,
        comment="单次查询最大返回行数"
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=30,
        comment="查询超时时间（秒）"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active, disabled"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )

    capability_workspace: Mapped["Workspace"] = relationship(
        primaryjoin="DataCapability.workspace_id == Workspace.id",
        back_populates="data_capabilities"
    )
    data_source: Mapped["DataSource"] = relationship(
        back_populates="capabilities"
    )
    bindings: Mapped[list["AgentDataBinding"]] = relationship(
        back_populates="data_capability", cascade="all, delete-orphan"
    )


class AgentDataBinding(Base):
    """Agent数据能力绑定表"""
    __table_args__ = {'comment': 'Agent数据能力绑定表 - 授权Agent使用特定数据能力'}
    __tablename__ = "t_agent_data_bindings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="绑定唯一标识符"
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id", ondelete="CASCADE"), nullable=False,
        comment="智能体 ID"
    )
    data_capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_data_capabilities.id", ondelete="CASCADE"), nullable=False,
        comment="数据能力 ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )

    agent_binding: Mapped["Agent"] = relationship(
        primaryjoin="AgentDataBinding.agent_id == Agent.id",
        back_populates="data_bindings"
    )
    data_capability: Mapped["DataCapability"] = relationship(
        back_populates="bindings"
    )


class DataAccessPolicy(Base):
    """数据访问策略表"""
    __table_args__ = {'comment': '数据访问策略表 - 定义行列级访问控制规则'}
    __tablename__ = "t_data_access_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="策略唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="策略名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="策略描述"
    )
    rules: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="策略规则（JSON），如行列级过滤条件"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="状态：active, disabled"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow,
        comment="最后更新时间"
    )


class DataQuery(Base):
    """数据查询审计表 - 记录所有数据查询"""
    __table_args__ = {'comment': '数据查询审计表 - 记录Agent数据能力调用的完整审计信息'}
    __tablename__ = "t_data_queries"

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("t_users.id"), nullable=True, index=True)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="查询记录唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True,
        comment="调用的智能体 ID"
    )
    data_capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_data_capabilities.id"), nullable=True,
        comment="调用的数据能力 ID"
    )
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_data_sources.id"), nullable=True,
        comment="目标数据源 ID"
    )
    query_text: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="实际执行的SQL（脱敏后）"
    )
    input_params: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="输入参数"
    )
    output_result: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="输出结果（截断）"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending",
        comment="状态：pending, success, failed, denied"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="执行耗时（毫秒）"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="错误信息"
    )
    source: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="调用来源：agent_runtime, meeting, conversation, manual"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )


# =============================================================================
# Agent 协作 (Agent Collaboration)
# =============================================================================
class AgentCollaboration(Base):
    """
    Agent 协作记录表 - 记录 Agent 之间的 @协作调用

    用于审计、统计 Token/Cost 和问题排查。
    """
    __table_args__ = {'comment': 'Agent协作记录表 - 记录Agent之间的@协作调用'}
    __tablename__ = "t_agent_collaborations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="协作记录唯一标识符"
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_conversations.id", ondelete="CASCADE"), nullable=False,
        comment="所属对话 ID"
    )
    source_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id", ondelete="CASCADE"), nullable=False,
        comment="发起协作的源 Agent ID"
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id", ondelete="CASCADE"), nullable=False,
        comment="被调用的目标 Agent ID"
    )
    task: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="协作任务描述"
    )
    known_facts: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="已知事实列表"
    )
    question: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="向目标 Agent 提出的具体问题"
    )
    constraints: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="约束条件"
    )
    expected_output: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="期望输出格式/内容"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending",
        comment="状态：pending, running, success, failed, timeout"
    )
    result_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="结果摘要"
    )
    result_content: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="完整结果内容"
    )
    result_sources: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="结果引用来源"
    )
    confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="结果置信度 0-1"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="执行耗时（毫秒）"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="错误信息"
    )
    call_depth: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="协作调用深度（防止无限循环）"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="协作开始时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="协作完成时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )

# Register identity tables referenced by ownership foreign keys.
from agentdevstu.security import models as _identity_models  # noqa: E402,F401

from agentdevstu.memory import models as _memory_models  # noqa: E402,F401
