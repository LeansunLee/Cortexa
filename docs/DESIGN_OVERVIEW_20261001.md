# Cortexa 产品设计与系统设计总览

**日期**: 2026-10-01
**性质**: 阶段性汇总文档，整合截至当前的产品设计、系统设计、关键子系统设计与工程经验
**口径**: 以当前代码实际状态（`src/cortexa/`，包名已由 `agentdevstu` 更名为 `cortexa`）为事实基础，产品设计以最新文档为准；历史文档间被替代的口径在附录中标注
**基线版本**: alpha v1.0.2609230000 之后已有约 28 个提交；本文包含 2026-10-01 未提交的回归修复内容

---

## 一、产品定位与演进

### 1.1 产品定位

Cortexa 是一个**企业 AI 智能体协作与真人工作闭环平台**：把企业知识、业务数据和专业 Agent 接入员工日常工作，通过对话、@协作、会议完成讨论，并把讨论结果转化为有负责人、交付物和验收过程的正式工作（Work）。Agent 是企业部门、职能角色或职业的数字化身，具有明确的人格、职责、能力边界和输入输出接口。

核心价值主张：让企业快速构建领域专家型 AI Agent，通过知识库和数据源赋予真实业务能力，通过对话和会议系统实现人机协作与多 Agent 协作，最终形成「讨论 → 工作 → 验收 → 沉淀」的闭环。

**已成立的主链路**：配置发布 Agent → 授权使用 → 对话/协作/会议 → 工作候选 → 人工确认分派 → 真人执行 → 提交验收 → 成果沉淀。**Agent 自动执行工作未接入**（Goal Runtime 已建设，默认关闭）。

**明确不承诺**：BPM/ERP 替代、无人监督执行、统一定时调度、完整 SSO、费用结算、全场景统一向量化、组织岗位等同于权限角色、会议待办自动变成正式工作。

### 1.2 演进脉络

| 时间 | 里程碑 |
| --- | --- |
| 早期 | LangGraph 多智能体 CLI 实验（researcher/writer/supervisor），后演进为 Web 平台 |
| 2026-09-09 | 联网搜索由自建 SearXNG 承接（127.0.0.1:8888），默认 provider 切为 searxng |
| 2026-09-16 | 项目基线、知识库设计与编码规范定版 |
| 2026-09-18 | 产品设计说明书成为产品总口径：主链路、角色权限、风险清单、四阶段路线图 |
| 2026-09-19 | **Memory 2.0** 上线：Agent-owned 长期记忆，主表扩展 17 列 + 4 张治理表，331 项回归通过 |
| 2026-09-20 | 记忆管理 UI 发布（弹窗体系、召回规则、筛选） |
| 2026-09-23 | 开发基线 v1.0.2609230000；知识库描述体系、多元预设头像、Token 消耗页增强 |
| 2026-09-23~24 | **Goal Runtime** Phase 0–5 设计与实施：目标解析、能力描述、有界执行循环、协作、Proxy 契约 |
| 2026-09-25 | 工作空间运行策略：预算与协作上限可按空间配置（`runtime_policy` JSONB） |
| 2026-09-28 | 对话级协作方式三选一（默认「不主动」）；全站 UI Design System 定版 |
| 2026-09 下旬 | 玻璃拟态 UI 大量迭代（liquid/frosted/clear 材质）、Python 包更名 `cortexa` |
| 2026-10 | 修复 9 月评审非会议 bug、10 月评审全部 7 个 GitHub issue；10-01 回归轮（issues #8/#10/#13）待提交 |

---

## 二、产品设计

### 2.1 核心概念与模块职责

| 模块 | 职责 |
| --- | --- |
| **Workspace 工作空间** | 成员与业务资源的隔离边界，含 Agent、知识、数据、组织、工作；带运行时策略（预算+协作上限） |
| **Agent 智能体** | 两类运行契约：LLM Agent（配置驱动构建提示词）、Proxy Agent（调外部 HTTP，受契约约束）；配置、草稿测试、发布、使用是不同动作 |
| **Knowledge 知识库** | 空间共享库 + Agent 独享库两级；人工维护的资料（区别于运行形成的 Memory） |
| **Data 数据源/数据能力** | PostgreSQL/MySQL/HTTP API 接入；加密凭证、Schema 同步、受约束查询能力、Agent 绑定 |
| **Conversation 对话** | 用户与 Agent 的交流上下文，SSE 流式；携带 Goal 与协作入口 |
| **Collaboration 协作** | @ 提及的跨 Agent 协作；各参与方独立任务、输入快照与依赖 |
| **Meeting 会议** | 多 Agent 多轮讨论，产生结论、分歧、待办；会议待办 ≠ 正式 Work |
| **Work 工作** | 候选经用户确认才成 Work；含负责人、验收人、优先级、截止时间、交付物、活动流水 |
| **Memory 记忆** | Agent 长期认知层；semantic/episodic/focus 三类；关注记忆仅作上下文参考，不建监控/提醒 |
| **Organization 组织** | 部门/团队层级、岗位、职责，用于负责人推荐（非自动派单）；岗位 ≠ 权限角色 |
| **Usage 用量** | 业务操作与模型调用明细的关联核算，仅超级管理员可见；非费用结算 |

### 2.2 账号、角色与权限

- 内置系统角色：用户管理员、空间管理员、Agent 开发者、普通使用者；超级管理员为特殊身份（模型用量仅其可见）。Agent 开发者默认权限**不含独立发布权**。
- 授权链 = 登录用户 + 系统权限 + 空间成员关系 + 空间角色 + 资源授权 + 数据所有权；后端为最终依据。
- 权限点分系统侧（用户、角色、空间创建、配置、审计、外部身份）与空间侧（空间/成员管理，Agent 的查看/创建/编辑/删除/发布/使用/运维，knowledge.manage/use、数据、工具、工作流、会议、记忆）。
- 管理身份不自动获得他人私有正文；会话、记忆、会议有用户所有权。

### 2.3 智能体（Agent）

**生命周期**：创建 → 配置 → 保存草稿 → 测试 → 创建版本 → 发布 → 对话/被调用。

**配置维度**（编辑器多 Tab）：基础信息（含上传裁剪头像 + 17 个多元人物预设 SVG）、人格（15 个性格标签）、职责（16 个预设角色，含研发与非研发岗）、工作边界、工作方式、Proxy 配置、输入/输出 JSON Schema（CodeMirror）、模型（temperature/max_tokens/system_prompt，工作空间默认模型 + 公共模型库）、版本快照、知识库（空间共享勾选 + 独享库）、数据能力绑定。

**System Prompt 自动拼接**：`你是{name}` + 人格特征 + 角色 + 职责 + 工作边界 + 工作方式 + 补充说明 + 参考知识（知识库检索）+ 可用数据查询能力。

**Agent 字段的 LLM 上下文使用**（9 月下旬增强）：角色/职责等字段标注了进入运行时上下文的方式；运行时使用业务角色与职责而非技术描述。

### 2.4 知识库

- **两级体系**：空间知识库（`agent_id=null`，共享，Agent 勾选绑定）与 Agent 独享库；独享库可推送共享库（复制语义，同源同目标幂等）。
- **存储分离**：DB 只存摘要（LLM 生成检索导向摘要，≤2000 字符，后台任务生成、失败回退截断）；全文存文件系统 `/opt/agentdevstu/data/documents/{doc_id}/content.txt`。
- **有效期规则**：上海时区自然日，截止当天有效，空值永久；过期/停用文档不进 Agent/RAG 检索，但有权用户可预览、下载、续期。
- **目录**：仅作用户分类不参与检索；禁止移动到自身/子孙；仅可删空目录；单文件上限 500MB。
- **检索**：两段式——先按 content 摘要定位文档，再对选中文档做全文窗口提取；摘要无命中回退全文扫描。独立 RAG 管线（BM25/HyDE/多查询/父子块/上下文检索）并存，未统一为单一向量引擎。

### 2.5 数据源与数据能力

架构链路：`数据源 → 凭证（加密） → 数据能力（查询模板+Schema） → Agent 绑定`。草稿试运行只读、限时、限行；结果区分业务总数/返回行数/截断；工具失败与截断必须对用户可见，不得用历史结果冒充实时查询。数据能力支持 SQL 参数化生成与试运行；行列级访问策略与调用全量审计。

### 2.6 对话与协作

- **对话**：SSE 流式逐 token 渲染；知识检索超时保护（10s）不阻塞对话；来源追踪；对话搜索/重命名/重新生成；历史按 Agent 分组；未命名对话按首轮消息自动生成标题（用户命名不被覆盖）。
- **协作三层控制**（最新口径）：
  1. 平台默认上限（历史默认：每次最多 3 个 Agent、深度 2、超时 120 秒）；
  2. 工作空间 `runtime_policy` 可配置 `max_collaborators` 等上限；
  3. 对话级三选一：**不主动 / 询问 / 主动**，受空间允许范围约束；新对话及未设置过的历史对话默认**不主动**；「询问」在运行时暂停并弹授权面板，@ 的参与者免确认。
- 接口：`GET /conversations/{id}/goal-options`、`PUT /conversations/{id}/collaboration-mode`。

### 2.7 会议（AI Meeting）

创建会议选择参与者 Agent 与主持人、设定轮数（默认 3）、必填会议目的、可传附件注入提示词；SSE 实时推送每轮讨论；主持人总结 + 冲突检测；结束后输出 TodoList。**会议待办不自动成为正式 Work**。

### 2.8 Work（工作闭环）

- **状态机**：`draft/pending/todo/in_progress/review/completed/rejected/cancelled`。真人流程 `todo → in_progress → review → completed`，退回必须填原因并回 `in_progress`；Agent 指派的工作停 `pending`（执行器未接入）。
- **候选提取**：从会话消息由来源 Agent 模型后台提取（40s 任务），`(conversation, message, fingerprint)` 唯一去重；**建议永不自动派发工作**。
- **关键规则**：负责人/验收人须为空间有效成员且不能同一人；关键写操作锁父工作行；删除私有会话不连带删已确认工作；工作来源不得绕过原会话权限。交付物类型 text/file/knowledge/memory，全文落盘、表存摘要；活动表记录完整审计。负责人推荐来自组织岗位档案，仅建议不派单。
- **Work 记忆沉淀**：验收本身不创建 Memory；用户人工选 Agent、填精炼认知、可关联交付物后提交。只有系统可证明的精确验收模板（“工作「标题」已验收通过。”）识别为 system Outcome；自定义结论属 explicit。

### 2.9 Memory 2.0（Agent 长期记忆）

详见第五节（系统设计）。产品层面要点：

- **Agent 是唯一记忆所有者**：每条 Memory 必有 agent_id；Workspace 提供隔离边界；用户可以是创建者/来源人/Subject，但不是 Owner。历史有 Agent 的记忆在授权链下共享使用。
- **普通认知自动治理，异常交人工**：对话后提取候选 → 治理（重复/合并/冲突/时间/风险）→ 入库；人主要处理冲突、高风险、低可信和治理失败。
- **认知与原始来源分开授权**：共享认知不授予私人会话、Work 或交付物的访问权。
- UI 统一用「记忆」术语：补充记忆、有效记忆、记忆内容、记忆变化；弹窗体系（详情/纠正/事实变化/召回规则），SearchSelect 筛选，召回规则带字段帮助。

### 2.10 组织与用量

组织模块维护部门/团队层级与成员职责档案（`t_org_units`、`t_workspace_member_profiles`），服务 Work 负责人推荐。用量模块把一次业务操作（对话、摘要、记忆提取等）与其触发的多次模型调用关联，落 `t_llm_usage_operations` / `t_llm_usage_calls`，提供趋势、下钻与分级单位展示（K/M/B），仅超管可见。

---

## 三、系统设计

### 3.1 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 + Vite + Vue Router + Pinia 式组合 API + axios + CodeMirror + Lucide 图标 |
| 后端 | Python 3.12 + FastAPI + Uvicorn（异步，SSE 流式） |
| 数据库 | PostgreSQL 14+（SQLAlchemy 2.0 async + asyncpg），56 张表 |
| LLM | LangChain（ChatOpenAI/Anthropic/Ollama），`astream` 流式，多供应商适配 |
| 检索 | BM25 + jieba 分词；RAG 管线（分块/嵌入/HyDE/多查询/父子块）；向量为预留 |
| 搜索 | 自建 SearXNG（127.0.0.1:8888） |
| 部署 | 单机 47.97.82.200（2 核 1.7GB），systemd `agentdevstu.service`，rsync 增量发布 |

### 3.2 后端模块（src/cortexa/）

| 子包 | 职责 |
| --- | --- |
| `api/` | FastAPI 路由层，约 20 个路由模块（见 3.5） |
| `agents/` | Agent 执行内核：LLM 构建、上下文组装、提示词、Proxy 执行、检索、用量 |
| `collaboration/` | @ 协作：提及解析、协作会话、草稿、后台任务 |
| `config/` | 全局配置 + LLM 供应商注册 |
| `data/` | 数据源适配、SQL 草稿、文档/PDF/图片提取、预览、后台作业（文件锁治理） |
| `db/` | engine、核心 ORM（26 表）、会议模型（6 表）、字段加密 |
| `memory/` | Memory 2 领域：models/schemas/policy/access/governance/evidence/lifecycle/retrieval/integration/service |
| `organization/` | 组织架构与成员职责档案 |
| `rag/` | RAG 管线：chunker/embedder/bm25_search/hyde/multi_query/parent_child/contextual_retrieval/retriever/summary/document_selection |
| `runtime/` | Goal Runtime：loop/state/policy/bindings/capabilities/adapters/observations/projection/collaboration/agent_executor/proxy/contracts/artifacts/store/shadow/goals/capture |
| `security/` | 身份与权限：用户/角色/会话（11 表）、审计、隔离、密码、身份 API |
| `tools/` | 工具集成：web_search/search/rag/meeting_tools/exec_tool/runtime |
| `usage/` | 管理员用量核算（`/admin/usage`） |
| `web/` | FastAPI 应用装配 + SPA 静态托管 |
| `work/` | 工作闭环：models/service/candidates/schemas（4 表） |
| `workflow/` | 工作流 DAG 引擎（框架已建，非完整交付承诺） |

### 3.3 前端架构（frontend/src/views/，17 页）

| 页面 | 路由 | 守卫 |
| --- | --- | --- |
| Dashboard | `/` | 登录 |
| Chat | `/chat` | agent.use |
| MyAgents | `/my-agents` | agent.use |
| AgentOperations | `/agent-operations/:agentId` | agent.operate |
| Agents | `/agents` | agent.read |
| Workflows / Tasks | `/workflows` `/tasks` | workflows.manage / tasks.manage |
| Meetings | `/meetings` | meeting.use |
| KnowledgeBases | `/knowledge` | knowledge.manage/use 任一 |
| DataSources | `/data-sources` | data.manage |
| Works | `/works`、`/works/:id` | 登录 |
| Workspaces | `/workspaces` | 登录 |
| Settings | `/settings` | config.manage |
| AccessAdmin | `/access` | admin |
| ModelUsage | `/model-usage` | superadmin |
| Personalization | `/personalization` | 登录 |
| Login | `/login`、`/change-password` | 公开 |

路由守卫：未登录跳登录；`must_change_password` 强制改密；按 permission/anyPermissions/superadmin/admin 校验。共享组件：`AgentMemory`、`MemoryDialog`、`MemoryFieldHelp`、`SearchSelect`、`AgentAvatar`、`WorkMemories`、`AgentResources`、`ConversationDebugPanel`、`PageHeader` 等。

### 3.4 数据模型（56 张表）

**db/models.py（26 张）**：`t_workspaces`（含 `runtime_policy` JSONB）、`t_agents`（含 collaboration/quality_policy/proxy_config JSON）、`t_agent_versions`、`t_agent_runs`、`t_knowledge_bases`、`t_knowledge_folders`、`t_documents`、`t_document_chunks`、`t_rules`、`t_tools`、`t_workflows`/`t_workflow_nodes`/`t_workflow_edges`、`t_tasks`/`t_task_runs`、`t_conversations`/`t_conversation_messages`、`t_memories`、`t_data_sources`、`t_data_credentials`（加密）、`t_data_schemas`、`t_data_capabilities`、`t_agent_data_bindings`、`t_data_access_policies`、`t_data_queries`、`t_agent_collaborations`。

**db/meetings.py（6 张）**：`t_meetings`、`t_meeting_participants`、`t_meeting_rounds`、`t_meeting_messages`、`t_meeting_conclusions`、`t_todo_items`。

**security/models.py（11 张）**：`t_users`、`t_login_sessions`、`t_roles`、`t_user_system_roles`、`t_workspace_members`、`t_workspace_member_roles`、`t_agent_grants`、`t_identity_providers`、`t_external_identities`、`t_security_audit_logs`、`t_protected_uploads`。

**memory/models.py（4 张治理表）**：`t_memory_evidences`（依据）、`t_memory_relations`（替代/纠正/合并/冲突/派生）、`t_memory_events`（治理审计）、`t_memory_issues`（待人工异常）。

**work/models.py（4 张）**：`t_works`、`t_work_candidates`、`t_work_deliverables`、`t_work_activities`。

**organization/models.py（2 张）**：`t_org_units`、`t_workspace_member_profiles`。

**usage/models.py（2 张）**：`t_llm_usage_operations`、`t_llm_usage_calls`。

**runtime/models.py（1 张）**：`t_runtime_goals`（Goal 运行状态）。

### 3.5 API 面（/api 前缀）

| 模块 | 前缀/路径 | 内容 |
| --- | --- | --- |
| workspaces | `/workspaces` | CRUD + 运行时策略 GET/PUT `runtime-policy` |
| agents | `/agents` | CRUD + 版本 + 发布 + 测试 + System Prompt 生成 |
| conversations | `/conversations` | CRUD + 消息 + SSE 聊天 + `message-route` + `goal-options`/`collaboration-mode` |
| goals | `/conversations/{id}/goals/*` | goals/stream、resume、status、result、candidates、authorization、collaborations/{action} |
| knowledge | `/knowledge` | 库/文档/目录 CRUD、上传、摘要、索引、有效期、全文内容 |
| data | `/data` | 数据源/凭证/Schema/能力/绑定/策略/查询审计 + SQL 参数化与试运行 |
| memories | `/memories` | Memory 2 管理（列表/详情/PATCH/corrections/supersessions/evidences/history/restore/purge） |
| agent-operations | `/agent-operations` | 记忆治理概览/异常/整理/召回规则 |
| works | `/works` | 工作派发/审批/拒绝/取消/指派推荐 + `POST /works/{id}/memory` |
| collaboration | `/collaboration` | @ 协作会话 |
| meetings | `/meetings` | CRUD + 启动/取消 + SSE 消息流 |
| tools / workflows / tasks | `/tools` `/workflows` `/tasks` | 各自 CRUD 与执行 |
| organization | `/organization` | 组织架构、成员档案 |
| identity | `/auth/*`、`/me/*`、`/admin/users|roles|permissions` | 登录登出改密、个人上下文、访问控制 |
| usage | `/admin/usage` | 用量核算（超管） |

### 3.6 关键工程机制

- **SSE 独立会话**：StreamingResponse 的 async generator 在请求结束后才执行，必须用 `async_session_factory` 新建独立 DB session，不能复用 request-scoped session（否则 `greenlet_spawn` 错误）。
- **大文本存文件系统**：文档全文、Goal 运行快照均落盘，DB 只存元数据/摘要/引用；Goal 快照随机文件名、0700/0600 权限、SHA-256、8MiB 上限、先落盘后提交引用。
- **后台任务修订号**：文档编辑/摘要/索引类后台任务用 `content_revision`/`summary_revision` 乐观校验，完成时 revision 不一致即丢弃，防旧任务覆盖新编辑。
- **文件锁治理**（10-01）：document_jobs 的 fcntl 锁在 Windows 回退进程内 asyncio.Lock；删文档清锁、孤儿锁清扫。
- **Uvicorn 限流**：`--limit-concurrency 50 --timeout-keep-alive 30 --backlog 64`，小内存服务器内存从 1.5GB 降至约 253MB。

---

## 四、Agent Runtime（Goal Runtime）设计

Goal Runtime 是 LLM 有界自主执行循环：用户在对话中提交任务式消息，经确定性路由进入 Goal 通道，由 Runtime 在预算与权限护栏内做多轮「推理 → 工具调用 → 观察」直至收尾。设计文档为 GOAL_RUNTIME_PHASE0–5 系列（2026-09-23/24），实施与文档已核对一致。

### 4.1 入口与路由

- 前端发送前调 `POST /conversations/{id}/message-route`：确定性解析器 `parse_goal()` 识别显式目标、成功标准、参与者与任务动作词；闲聊/附件/Proxy 主 Agent/开关关闭走普通对话。该步不调模型、不授权。
- 功能开关（config.yaml，仓库保守默认）：`goal_shadow_enabled=true`（影子跟踪）、`goal_execution_enabled=false`、`goal_collaboration_enabled=false`、`goal_proxy_enabled=false`；生产环境显式开启。

### 4.2 领域模型与状态机

- `t_runtime_goals`：workspace/owner/conversation/initial_message/agent、`idempotency_key`（(workspace,owner,key) 唯一）、status、`revision`（CAS 乐观并发）、state JSONB（≤64KiB）、artifacts JSONB、completed_at。
- 状态：`RUNNING / COMPLETE / BLOCKED / WAITING / FAILED`；next_action：`CONTINUE / ASK_USER / REQUEST_APPROVAL / ASK_HUMAN / RETRY / REPLAN / FAIL / NONE`。
- Action 三阶段 `started/completed/unknown`：外部调用前先持久化 started；**结果未知（unknown）的动作禁止自动重放**，避免重复副作用。

### 4.3 预算与策略（五层）

`平台硬上限 → config.yaml → Workspace.runtime_policy → Agent.quality_policy → 单次 Goal 请求`，逐层只能收紧。预算覆盖总时长、模型调用、工具调用、Web 调用、Agent 调用、协作者数、递归深度、步骤、重规划、失败次数、上下文与输出（当前代码默认 agent_calls=3、max_replans=3、output_tokens=16384、web_calls=10）。预算生命周期四阶段：

| 阶段 | 行为 |
| --- | --- |
| NORMAL | 提供全部已绑定且获准的能力 |
| CONSERVE | 收缩到尚未满足的必需业务能力与未用显式协作者 |
| FINALIZING | 不再给工具，只要求基于已有结果收尾并说明缺失 |
| EXHAUSTED | 停止并记录耗尽项 |

保留 1/4 输出额度（上限 4096）用于收尾。恢复时重新读策略，限额只收紧不重置已耗额度。

### 4.4 执行循环（GoalLoop.run）

`while RUNNING: 重验授权 → 剩余时长检查 → 预算相位 → 一次 astream 推理（原生 tool_calls 或最终文本）→ 工具整批校验 → 执行 → Observation → budget.observe()`。无独立 Planner/Evaluator 模型调用。

工具调用顺序：工具名必须属于本轮绑定能力 → 风险/确认检查（高风险转 WAITING+REQUEST_APPROVAL）→ Schema 校验（默认值确定性修复；缺必填记 NOT_READY 向用户补参）→ 数据/Agent 能力再验权限与协作策略 → 请求指纹去重 → 预算预留 + Action started → 执行 → 投影为有大小上限的模型可见结果（完整私有结果落快照）。

Observation 七态：`SUCCESS / EMPTY / PARTIAL / NOT_READY / FAILED / TIMEOUT / UNKNOWN`。最终文本收尾前校验：非空、未被长度截断、必需数据能力已取得（否则不能宣称完成）；有成功观测时失败降级为 partial 收尾声明，完全无成功观测才硬停。无效 tool call 整批拒绝，消耗有限重规划预算（默认 3 次）。

### 4.5 Agent 协作与 Proxy 契约

- **协作**：Agent Capability 委托给子 GoalLoop。三档自治 `EXPLICIT_ONLY / ASK_BEFORE_COLLABORATION / AUTONOMOUS`（逐层收紧）；确定性发现（Workspace+权限过滤后本地词项匹配排序，默认 3 上限 5）；授权带 revision+`decision_fingerprint` 幂等，**拒绝在本 Goal 内持续生效**；授权来源 USER_EXPLICIT / USER_APPROVED / RUNTIME_AUTONOMOUS。子 Agent 只收自身配置+委托任务+契约 inputs+主模型选中的 Observation，不传主 Agent 私有上下文；子预算预占共享额度并实时记账；深度限制 + A→B→A 环路检测。
- **Proxy 契约**：Proxy 可作被协作方，不能作 Goal 主 Agent。默认拒绝投影：字段来源白名单 `explicit/goal_task/observation_facts/observation_summary`；五类上下文恒不外发（完整会话/记忆/知识/他 Agent 上下文/主 System Prompt）；输入预算默认 4000 字节；每 Action 单次 HTTP、不重试；超时/取消 → unknown；缺显式字段 → WAITING 补参续跑。

### 4.6 边界

Goal 主 Agent 仅支持 LLM Agent；有附件走普通对话。权限、预算、Schema 校验全在服务端，模型选择不能绕开。启动时不自动迁移数据库（`scripts/migrate_goal_runtime.py` 需显式 `--apply`）。Phase 6（LLM Gateway/purpose 路由）文档化但未实施。

---

## 五、Memory 2.0 设计（Agent 长期记忆）

### 5.1 领域模型

主表 `t_memories`：workspace_id + 非空 agent_id（复合外键指向 t_agents，防跨空间错配）、type（semantic/episodic/focus）、kind（fact/preference/relationship/decision/event/observation/outcome/concern/other 九种）、content、importance/confidence（0–1）、status、subject_type/id/name、claim_key、source_mode（explicit/system/inferred）、occurred_at、valid_from/valid_to（[from, to) 带时区）、expires_at、risk_level、has_conflict、revision、normalized_hash、search_terms（JSONB+GIN）、embedding（预留）。owner_user_id 仅作来源兼容，不参与隔离。

四张治理表：Evidence（多依据，`memory+evidence_key` 唯一，root_keys 识别同根来源防互证抬信）、Relations（supersedes/corrects/merges/conflicts/derived_from，禁自环，派生链深度>16 拒绝）、Events（幂等键审计）、Issues（未关闭去重）。

### 5.2 生命周期与治理

状态：`candidate → active`，及 `superseded / expired / retracted / archived / rejected`；冲突以 `has_conflict`+Issue 表达，不占生命周期。

写入治理：先做确定性规范化重复检查，再在同 Agent 同类兼容 Subject 候选中判断重复（保 Canonical 补 Evidence）/补充/时间更新/冲突/独立；可选模型有界判断（最多 20 条候选、15s 超时），失败不伪装成功。敏感内容拦截，高风险需核验。**显式更正**（用户说“更正/作废”，10-01 增强）：立即 superseded 旧记忆并建 supersedes 关系，不再交模型仲裁。正式纠正要求原因+expected_revision+幂等键；事实正文不能 PATCH 悄悄覆盖；真冲突保留双方交人工裁决，召回时整组注入或整组不注入。Consolidation 分批整理（单批 ≤100 条，约 20 秒返回续页游标），无持久调度器。

### 5.3 检索与 Context

权限与状态过滤先行；关键词用 jieba + 有限同义词，JSONB/GIN 词项交集（非 BM25、非向量）；三类各有界候选通道。排序公式（工程策略，非评测最优）：

| 类别 | 公式 |
| --- | --- |
| semantic | 0.60 相关性 + 0.25 置信度 + 0.10 Subject + 0.05 Importance |
| episodic | 0.60 相关性 + 0.15 置信度 + 0.15 事件新近 + 0.10 Importance |
| focus | 0.60 相关性 + 0.20 Subject + 0.10 置信度 + 0.10 Importance + 有界 Focus Boost |

Agent 召回配置默认：top_k=5、token_budget=1200、candidate_limit=200、relevance_threshold=0.20、focus_boost=0.10、semantic_judgment=true、extract_limit=5（各有范围）。Context 分稳定认知/相关历史/当前关注/不确定与冲突四段；inferred、低可信、冲突明确标注不得视为确定事实。

### 5.4 来源、删除传播与集成

Evidence 逐条鉴权，无权不泄露原来源。来源删除/替换传播：无可用依据 → 清正文存 tombstone；仍有他据 → 降信 + `source_review_required` 暂停召回；上游纠正沿 derived_from 下游标记待复验；隐私清除需 `workspace.manage` 二次确认。有记忆的 Agent 与空间删除受保护性阻止。

集成：对话提取任务在响应链外、独立 session、登记 pending/success/failed、防重复、失败可 retry；协作成功可为双方 Agent 蒸馏认知并验证上游依据；Work 沉淀全人工（见 2.8）。**Meeting 与 Memory 本期无新集成。**

已知边界：无持久任务恢复（重启遗留任务需重试）；关键词+有限模型治理非完整语义检索；未启用 Embedding/知识图谱/GraphRAG；无大规模容量与 P95 基准。

---

## 六、安全与隔离设计

- 身份：本地账号 + 登录会话（`t_login_sessions`）+ 强制改密流；外部身份提供方与外部身份表为 SSO 预留。
- 授权：系统角色（`t_roles`+`t_user_system_roles`）、空间成员与空间角色（`t_workspace_members`+`t_workspace_member_roles`）、Agent 使用授权（`t_agent_grants`）。
- 审计：`t_security_audit_logs` 全量安全审计；数据能力调用另有 `t_data_queries` 审计。
- 隔离：security/isolation + catalog + http 统一路由权限；跨空间资源访问以复合外键与查询过滤双重约束；凭证列级加密（db/encryption）。
- 上传保护：`t_protected_uploads`；受保护上传独立管理。

---

## 七、UI 设计系统（2026-09-28 定版）

- **架构**：Design System → Semantic Tokens → Theme Tokens → Components → Pages。业务页面只定结构/内容/状态；`utils/theme.js` 生成令牌、`applyTheme` 写根节点；`utils/appearance.js` 管浅色/深色/跟随系统（`data-theme`+`color-scheme`）。主题切换只更新令牌，不重建组件。
- **主题体系**：165 套预设主题——纯色 98（7 类×14）、撞色 14、渐变 14、玻璃 14、纹理 25，各类另带自定义。三种外观（浅/深/跟随系统）与主题相互独立，按账号存浏览器，首渲染前恢复防闪烁。
- **玻璃材质**：Glass 0（普通卡片保持实体）→ Glass 1（重要面板弱玻璃）→ Glass 2（导航/悬浮）→ Glass 3（菜单/弹窗覆盖层）。液态（约 60% 半透明 + blur 12px，锐利亮边）与磨砂（约 96% 半透明 + blur 38px）两质地。**浮层穿透必须用「增强模糊 + 适度底色透明度」解决，禁止提高不透明度**；`backdrop-filter: url(#svg)` 在 Chromium 真实页面静默失败，已回退，不得作为实现依赖。
- **布局**：无全局顶栏；侧栏 240px（900px 以下 200px，640px 以下 72px 图标导航），账号入口固定侧栏底部；内容区顶部 44px 页面标签栏（多标签保状态、键盘可操作、切空间/用户清理）；`.page-content` 唯一提供边距（桌面 24/32px → 640px 以下 16/20px）；控件基础高度 40px、间距 4px 基数。
- **语义变量强制**：所有页面只准用 `--bg/--surface*/--text*/--border/--success/--danger/--overlay` 等，禁止固定白底与仅浅色可读的灰字；状态不能只靠颜色。回归测试：`card-theme-audit`、`theme-controls`（6 材质×2 外观 12 组）、`personalization`、`knowledge-controls` 等 browser 测试。
- **预设头像**：17 个多元化人物 SVG，`AgentAvatar.vue` 内联渲染跟随主题；新增预设须同步 `presetAvatars` 列表。
- **鼠标边缘泛光**：响应 130px（磨砂 95px）、缓动 150ms、按距离平方衰减、控件独立计算（`utils/glassLighting.js`）；禁止全局同步发光。

---

## 八、部署与运维

| 项目 | 值 |
| --- | --- |
| 服务器 | 47.97.82.200（2 核 1.7GB） |
| 项目路径 | `/opt/agentdevstu/`（服务器目录名沿用旧包名，本地包已更名 `cortexa`，部署靠 rsync+PYTHONPATH 对齐，服务器配置与仓库存在已知漂移） |
| 数据库 | PostgreSQL `agentdevstu`，5432 |
| 服务 | systemd `agentdevstu.service`，EnvironmentFile `/opt/agentdevstu/.env` |
| 前端构建 | `cd frontend && npm run build` → 静态产物随后端托管 |
| 发布 | rsync（--checksum 增量）+ `systemctl restart agentdevstu`，部署后检查服务状态与页面 |
| 文档/快照存储 | `/opt/agentdevstu/data/documents/`、`/opt/agentdevstu/data/runtime_goals/` |

迁移纪律：Memory 2、Goal Runtime 迁移脚本均为默认只读 preflight、显式 `--apply`、事务 + advisory lock、私有备份、可回滚；应用启动不自动改表。不私自修改数据库表结构，需要时提前告知。

---

## 九、当前状态（2026-10-01）

### 9.1 已提交（基线后 28 个提交）

Goal Runtime 全量落地与文档化；Python 包更名 cortexa；对话调试分支/上下文暴露（`/me/conversation-debug`）；Agent 字段 LLM 上下文标注；约 12 个玻璃 UI 迭代提交；聊天与目标协作流加固；重试保留无限目标预算；9 月评审非会议 bug 修复；10 月评审 7 个 GitHub issue 全部修复。

### 9.2 未提交（10-01 回归轮，+340/−32，新增 tests/test_20261001_issue8_13_fixes.py）

1. **#8 裸工具调用标记清洗**：识别并剥离模型以纯文本输出的 `<tool_call>` 标记，拒绝后引导模型自然语言作答（runtime/loop、agent_executor、prompts）。
2. **#10 记忆显式更正**：用户显式更正时旧冲突记忆立即 superseded 并建 supersedes 关系（memory/governance、service、prompts）。
3. **#13 文档作业锁治理**：Windows 锁回退、删文档清锁、孤儿锁清扫、PDF 提取锁名修正（data/document_jobs、api/knowledge）。
4. **无文字文件与失败信息友好化**：无法提取文字的合法文件改为「文件信息摘要」并标记 unsupported；提取失败按类型给出可读原因；goals.py 新增 6 条结构化停止话术；参与者模型配置错误返回结构化协作失败。

### 9.3 功能开关现状（仓库 config.yaml）

`goal_shadow_enabled=true`；`goal_execution_enabled / goal_collaboration_enabled / goal_proxy_enabled=false`（生产服务器按需显式开启）。即：Goal 运行时已建成但默认关闭，普通对话为主路径。

### 9.4 主要待开发与已知限制

- Agent 自动执行工作（Work 指派的执行器）、Work 与 Goal Runtime 打通。
- 工作流引擎完善、工具系统接入实际工具、规则库实现。
- 向量检索（BGE-M3 + Ollama）替代/增强 BM25；全场景统一向量化不做。
- Memory：持久任务调度、语义检索评测题库、大规模容量与 P95 基准、Experience 体系。
- 对话：消息分页加载、Markdown 渲染优化、导出、消息编辑。
- 多模态、Agent 市场、批量导入导出、Office 在线编辑（OnlyOffice 调研后暂缓）、Liquid Glass 折射（待浏览器成熟）。
- Phase 6 LLM Gateway（purpose 路由/升级 fallback）仅文档化。

---

## 附录：文档索引

| 文档 | 日期 | 定位 |
| --- | --- | --- |
| PRODUCT_DESIGN_20260918.md | 09-18 | **产品总口径**（主链路、角色权限、路线图） |
| PRODUCT_DESIGN_20260919.md | 09-19/20 | Memory 2.0 实施基线（替代 9-18 中 Memory 章节） |
| MEMORY_2_DESIGN_PROPOSAL_20260919.md | 09-19 | Memory 2 数据库与领域设计留档（已批准） |
| MEMORY_2_AUDIT_20260919.md | 09-19 | Memory 升级前快照 |
| KNOWLEDGE_BASELINE_20260916.md | 09-16 | 知识库设计与编码规范（现行） |
| PROJECT_BASELINE_20260916.md | 09-16 | 上期项目盘点（被 9-18 吸收） |
| GOAL_RUNTIME_DB_PROPOSAL / PHASE0–5（20260923–24） | 09-23/24 | Goal Runtime 设计与实施记录（Phase 6 未实施） |
| AGENT_RUNTIME_FLOW.md | 10-01 更新 | Goal Runtime 当前执行流程（按代码；文中旧包名 agentdevstu 应读作 cortexa） |
| WORKSPACE_RUNTIME_POLICY_20260925.md | 09-25 | 空间级预算与协作上限（现行） |
| CONVERSATION_COLLABORATION_20260928.md | 09-28 | 对话级协作三选一（最新口径） |
| UI_LAYOUT_GUIDELINES.md | 09-08 起，09-28 定版 | 全站布局与 UI Design System（现行） |
| ALPHA_v1.0.2609230000.md（及更早两版） | 09-23 | 开发基线：架构、API、经验总结 |
| SEARXNG_20260909.md | 09-09 | 自建搜索部署验收 |
| UI_AUDIT / CHAT_ROUTING_DEBUG | 09-24/28 | 专项审计与排查记录 |

> 注：本文撰写时工作区存在 10-01 回归轮未提交改动（见 9.2）；如后续提交，以代码为准。
