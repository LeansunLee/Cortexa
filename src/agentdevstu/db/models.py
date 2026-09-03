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
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
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


# =============================================================================
# 智能体 (Agent)
# =============================================================================
class Agent(Base):
    """
    智能体表 - AI 数字员工的核心配置
    """
    __table_args__ = {'comment': '智能体表 - AI 数字员工的核心配置，定义角色、职责、能力边界和输入输出接口'}
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
        back_populates="agent"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="agent"
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
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
    """
    记忆表 - 智能体的短期/长期记忆
    """
    __table_args__ = {'comment': '记忆表 - 智能体的短期/长期记忆，存储对话和任务中积累的知识'}
    """
    记忆表 - 智能体的短期/长期记忆
    
    存储智能体在对话和任务中积累的知识。
    支持短期记忆（会话内）和长期记忆（跨会话）。
    """
    __tablename__ = "t_memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid,
        comment="记忆唯一标识符"
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_workspaces.id"), nullable=False,
        comment="所属工作空间 ID"
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_agents.id"), nullable=True,
        comment="关联的智能体 ID"
    )
    type: Mapped[str] = mapped_column(
        String(32), default="short_term",
        comment="类型：short_term(短期), long_term(长期), semantic(语义)"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="记忆内容"
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="元数据，如来源、重要性等"
    )
    embedding: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="向量嵌入，用于语义检索"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="创建时间"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="过期时间（用于短期记忆）"
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="memories"
    )
    agent: Mapped["Agent"] = relationship(
        back_populates="memories"
    )
