# Memory 2.0：Phase 0 当前实现审计

日期：2026-09-19。状态：只读审计完成，Memory 2.0 尚未开发。

配套方案：[数据库与领域模型方案](MEMORY_2_DESIGN_PROPOSAL_20260919.md)。本文描述现有代码；配套方案描述拟开发行为，两者不能混用。

## 1. 审计依据与执行边界

- 本地代码基线：`ab65808`，分支 `main`。
- 阅读依据：README、[2026-09-18 产品设计](PRODUCT_DESIGN_20260918.md)、[2026-09-16 项目基线](PROJECT_BASELINE_20260916.md)、[UI 规范](UI_LAYOUT_GUIDELINES.md)、仓库实际文件 `Agents.md`，以及下列实现与测试。
- 需求依据：用户最新“Agent 为唯一认知主体”版本及后续确认。此前 Personal / Agent Shared / Workspace Shared 三分模型已废弃。
- 用户已确认：Agent Memory 对所有合法使用该 Agent 的用户共享；历史有 Agent 的记忆同样共享；无 Agent 的历史记忆作为开发脏数据删除；Work 只能人工发起沉淀。
- 本轮未连接开发数据库检查存量数据或实际索引，未执行测试、DDL、迁移、数据删除、构建或部署。字段和约束描述来自 ORM，不声称线上数据库完全一致。
- 本地 `frontend/src/views/AgentOperations.vue` 仍显示既有未提交差异；用户说明该布局已经提交发布。本轮保留其工作副本，不重新提交、不丢弃、不推定服务器状态。
- 本轮仅新增审计与方案文档，未修改业务代码。旧文档中的测试通过数属于旧轮次，不作为本轮测试结果。

## 2. 当前 Memory 模型

位置：[db/models.py](../src/agentdevstu/db/models.py)，类 `Memory`，表 `t_memories`。

| 字段 | ORM 类型/空值 | 当前含义与使用 |
| --- | --- | --- |
| id | UUID，主键 | 记忆标识 |
| owner_user_id | UUID，可空，FK → t_users.id，索引 | 当前私有所有权；普通业务写入由 Actor 钩子填充 |
| workspace_id | UUID，非空，FK → t_workspaces.id | 工作空间隔离 |
| agent_id | UUID，可空，FK → t_agents.id | 指定 Agent；为空时可在同一用户当前空间的不同 Agent 中召回 |
| type | String(32)，非空，默认 semantic | API 支持 semantic / episodic / focus；ORM 注释落后于 API |
| content | Text，非空 | 记忆正文 |
| importance | Float，非空，默认 0.5 | 已参与排序 |
| confidence | Float，非空，默认 0.5 | 已保存和输出，未参与检索评分 |
| status | String(32)，非空，默认 active | active / archived / rejected 注释；部分 API 未限定枚举 |
| source_type | String(32)，非空，默认 conversation | 单一来源类型；历史注释不覆盖实际 Work/manual 等写入 |
| source_id | UUID，可空，无外键 | 单一业务来源 ID，不保证来源存在或可访问 |
| last_accessed_at | TIMESTAMPTZ，可空 | 召回时更新 |
| access_count | Integer，非空，默认 0 | 召回时累加 |
| metadata_json | JSON，非空，默认空对象 | 可扩展元数据；未发现 Memory 专属治理逻辑使用 |
| embedding | JSON，可空 | 预留，Memory 检索未使用 |
| created_at | TIMESTAMPTZ，非空，server now | 系统保存时间 |
| updated_at | TIMESTAMPTZ，非空，server now | 只定义默认值，无统一自动 onupdate；部分 API 手动更新 |
| expires_at | TIMESTAMPTZ，可空 | 预留，当前检索没有过滤它 |

**枚举与索引：**type/status/source_type 均为字符串，不是 PostgreSQL Enum。Memory ORM 显式声明的二级索引只有 owner_user_id；另有主键索引。未声明 Workspace、Agent、状态、时间、Subject 的复合索引，不据此推定实库不存在额外手工索引。

**关系与删除：**Memory 有 Workspace、Agent relationship；Workspace.memories 配置 `all, delete-orphan`；Agent.memories 未显式配置相同删除级联。Source 没有外键，也没有证据子表。Agent 删除时存在 ORM 尝试清空 agent_id 的风险，是否实际成功还受其他外键影响，未做删除实验。

## 3. 当前 Ownership 与安全机制

依据：[security/isolation.py](../src/agentdevstu/security/isolation.py)、[access.py](../src/agentdevstu/security/access.py)、[http.py](../src/agentdevstu/security/http.py)、[catalog.py](../src/agentdevstu/security/catalog.py)。

1. Memory 属于 `PRIVATE` 模型，查询自动叠加 `owner_user_id == actor.user_id`，管理员也不会自然看见其他用户的 Memory。
2. Workspace 字段按当前 Actor 过滤；运行时 Agent 还受发布状态、成员关系、Agent Grant 和 `agent.use` 限制。
3. 通用 before_flush 钩子给带 owner_user_id 的新对象赋当前用户，并禁止操作其他所有者的数据。
4. `/api/memories` 经 HTTP 权限路由要求 `memory.manage`，其当前含义是“管理自己的记忆”，普通成员默认拥有。
5. Agent 运维入口要求 `agent.operate`、`agent.use` 和具体 Agent 使用权；其 Memory 查询、更新还显式核验 owner_user_id。
6. 所谓“空间级记忆”实际仍为用户私有，只是不指定 Agent。不能将该注释解释成全空间共享。
7. ORM Actor 缺失时不执行自动隔离。未来 Consolidation 不能直接以无 Actor session 扫表运行。
8. SSE 定期重新校验身份与授权，已有独立 session/ContextVar 机制可复用；仍需覆盖新写入链、治理和召回。

**升级影响：**需要同时调整 Memory 读过滤、写钩子、Agent 运维查询和通用 API 鉴权。只移除 `PRIVATE` 中的 Memory，会失去现有所有权限制，却没有补上 Agent 隔离，不能作为完整实现。

## 4. 当前写入链

### 4.1 Conversation 自动提取

位置：[api/conversations.py](../src/agentdevstu/api/conversations.py)、[memory/service.py](../src/agentdevstu/memory/service.py)。

- LLM 流式回答持久化并发送 `done` 事件后，调用 extract_memories，超时 40 秒。
- 输入包含近期历史、当前用户消息和助手回答；内容有截断。Service 最多使用末 10 条消息，每条取前 500 字符。
- Prompt 要求只提取跨会话有价值的信息，支持三类记忆，明确 Focus 不代表监控。
- 返回临时 Python 字典列表，仅粗验 content、type 与 importance ≥ 0.5，没有持久化 Candidate 状态。
- store_memory 将结果直接保存为 active，单一来源为 conversation + conversation_id，未记录精确消息及陈述者。
- 未做重复、冲突、Subject、有效时间、Evidence 或权限去敏判断；用户陈述与助手推断可能混在同一提取输入中。
- 提取仍在流生成器生命周期内，非可靠后台队列；断线、取消、进程退出可能中断。
- 未发现同步发送、重新生成和 Proxy 回答具有完全相同的自动提取调用。它们不能被描述成统一写入链。
- 对话压缩摘要是上下文管理，不等于自动持久化为一条 Memory。
- 提取 Prompt 当前把“决策、结论”列在 episodic 中，与新需求 semantic + decision 有口径差异；历史类型不可无依据批量改写。

### 4.2 手工保存

- `/api/memories` POST：可不传 agent_id，直接 active，source_type=manual；默认 confidence=0.8。
- Agent 运维 `/{agent_id}/memories` POST：绑定当前 Agent、当前用户，直接 active/manual。
- 通用 Memory API 没有“从特定对话消息保存”的结构化字段；不能称为已经具备精确 message provenance 的手工保存。

### 4.3 Work → Memory

位置：[api/works.py](../src/agentdevstu/api/works.py)、[work/service.py](../src/agentdevstu/work/service.py)、[WorkMemories.vue](../frontend/src/components/WorkMemories.vue)。

- 完成验收的 Work 由人主动沉淀，前端选择目标 Agent、category、content，可以逐条保存多项。
- 后端核验 Work 可见性、完成状态、验收角色与 memory.manage，再核验目标 Agent 使用权。
- Work 锁内比较历史活动 `(agent_id, content, type)`，相同重复点击返回已有 memory_id。已有精确幂等，不是语义去重。
- 保存 active、importance=0.7、confidence=0.9、source_type=work/source_id=Work ID；所有者仍是当前用户。
- WorkActivity 记录 memory_id、目标 Agent、类型和正文，存在正文副本。
- 未直接关联最终交付物、验收活动、人工修改链；验收操作本身不自动写 Memory。
- 新需求保留最后一点：Work 自动验收事件不能绕开“人工沉淀”开关。

### 4.4 Collaboration

位置：[collaboration/manager.py](../src/agentdevstu/collaboration/manager.py)。

- 目标 Agent 在独立 session 中召回自己的及 agent_id 为空的可见 Memory，Top 5。
- 未发现独立 Collaboration → Memory 的存储入口。
- 主 Conversation 的提取可能读到含协作结论的最终回答，但来源仍记作 Conversation，不构成可验证的 other_agent_memory 关系。
- 协作记录已有 result_sources 等扩展载体，可用于后续记录实际采用的来源，不能把“召回过”当成“支持结论”。

### 4.5 其他入口

全局检索确认直接 Memory 写入集中于上述 Service、通用 API 与 Agent 运维 API。没有独立 Tool/Data/Knowledge 自动采集 Memory 服务。Meeting 未发现新需求所述提取和召回接入，本期保持不接入、不修改。

## 5. 当前 Retrieval 与 Prompt

调用点：LLM 对话流、`agents/context.py` 的同步/重新生成参考构建、Collaboration 目标 Agent。

| 环节 | 实际行为 |
| --- | --- |
| SQL 范围 | workspace 精确匹配 + active + 当前 agent_id 或 NULL |
| 用户范围 | 依赖 ORM Actor 私有过滤，不在 Service 参数中明确传入 |
| 候选集合 | 把上述 SQL 可见记录全部取到 Python |
| 文本匹配 | jieba 分词，词长至少 2，正文包含词则加 1 |
| 评分 | 关键词命中数 + importance × 0.3 |
| 相关性门槛 | score > 0；importance 可单独使无关键词命中记录入选 |
| 类型权重 | 三类完全相同，无相关 Focus 专用 Boost |
| 时间/可信度 | 不使用 expires_at、confidence、事实有效区间 |
| Top N | 默认 5，主要调用点也传 5 |
| 检索技术 | Memory 未使用 BM25、Embedding、向量索引 |
| 访问统计 | 修改访问次数和时间并 flush；独立调用 session 未必提交，持久性不一致 |

输出为“相关记忆”下的 `[事实] / [事件] / [关注]` 正文列表。Service 注释写 system prompt，但实际通过 `reference_message` 作为 user-role 的参考数据注入；平台规则明确参考内容不是指令。

通用参考封装有 12,000 字符上限，当前没有专属 Memory Token Budget，也没有 Evidence、时间、不确定性分组。

## 6. 当前 Trace、审计和运维配置

- 对话 debug 开启时，记录 query、Agent/Workspace、耗时、Top 5 入选 ID、type、content、importance、confidence、scope 和 injected_context，持久化到助手消息 metadata_json.debug_trace。
- 未记录完整候选、过滤原因、相关度、最终分数、事实时间和派生关系；也不是所有 Runtime 的统一追踪。
- `_debug_safe` 对凭证形状字段脱敏并截断，不会自动判断 Memory 正文是否适合共享。
- 调试 UI 基于现有 debug 开关；不能据此认定已有独立的 Memory 运维调试权限。
- 记忆提取已有 `usage_action(memory_extract)` 模型用量归因。用量表刻意不保存业务正文，不适合作为 Memory 正文 Trace 仓库。
- 安全 AuditLog 可复用记录敏感操作，但它不是当前 Memory 版本历史。
- Agent.memory_config JSON 已存在，本次搜索未见完整配置读写与治理消费链，可扩展使用。

## 7. 当前 UI 与 API

| 入口 | 已有 | 缺少 |
| --- | --- | --- |
| AgentResources 记忆区域 | “我的 Agent 记忆”、三类筛选、显示归档、新建、直接编辑、归档、重要性、正文与时间 | 共享语义、搜索分页、详情、Evidence、Confidence 展示、Subject、有效期、纠错、冲突、治理统计 |
| Agent 运维 | 复用资源组件，按 Agent 授权进入 | 当前仍只展示操作者自己的 Memory |
| WorkMemories | 人工选择 Agent/类型、编辑多条内容、展示沉淀活动 | 精确验收与交付证据、Candidate/合并/冲突结果表达 |
| Workspace | 没有独立 Memory 管理页 | 本期也不新增 |

通用 `/api/memories` 支持 POST/GET/单项 GET/PATCH/DELETE。列表无文本搜索和分页，默认排除 archived（不是只取 active）。PATCH 可直接覆盖 content 和任意字符串 status；DELETE 实际归档，并未物理删除。Agent 运维 API 有更严格输入校验，但同样覆盖正文。

## 8. 来源与对象删除影响

| 操作 | 当前代码事实 / 边界 |
| --- | --- |
| 删除 Conversation | 删除会话；未处理派生 Memory。因 source_id 无 FK，Memory 可能继续召回其内容 |
| 删除/重生成消息 | 未见 Memory 精确消息关系或失效传播 |
| Meeting 删除 | 未发现常规删除 API；不为本期扩展 |
| Work 取消 | 是业务状态变化；未见通用 Work 删除入口，不能当成隐私删除 |
| User 停用 | 撤销会话/身份可用性，不等于派生 Memory 自动清理；未见普通物理删除入口 |
| Agent 删除 | 当前可空关系存在丢失归属风险，升级需要与非空 Agent 所有权一致 |
| Workspace 删除 | ORM 有 Memory delete-orphan；实库完整级联及多用户删除行为未验证 |

Memory、WorkActivity、Conversation debug 等都可能保存副本。未来删除传播不能只修改 Evidence.source_status，同时留下仍可召回的正文和追踪快照。

## 9. 当前测试与需要改变的断言

| 测试 | 当前覆盖 | 新需求影响 |
| --- | --- | --- |
| test_memory_types.py | 三分类、Focus、importance 边界、直接编辑及 Prompt 标签 | 保留分类；正文编辑用纠错接口替代 |
| test_agent_operations.py | 运维权限、跨 Agent/跨用户拒绝、归档保留记录 | “跨用户即拒绝”改为按 Agent 授权和治理权限判断 |
| test_identity_security.py | ORM 用户/空间私有隔离、身份安全 | 只调整 Memory 共享断言，Conversation/Meeting 等继续私有 |
| test_work.py | 完成后人工沉淀、类型、重复点击幂等、业务权限 | 增加 Evidence 与治理结果，不增加验收自动写入 |
| test_collaboration_context.py | 目标 Agent 资源及协作上下文边界 | 增加目标 Agent 独占召回与跨 Agent 证据引用 |
| test_conversation_debug.py 等 | 对话调试、流式和参考注入 | 增加有界 Trace、管理权限与删除传播 |

现有用例不能证明 Memory 2.0 已通过。需要新增多证据、并发去重、时间查询、冲突、纠错、异常队列、迁移及共享权限回归；数据库集成只允许使用隔离可丢弃数据库。

## 10. Gap 与本期修改边界

| 分类 | 内容 |
| --- | --- |
| 已有 | 三类记忆、提取/保存/管理/检索/注入、人工 Work 沉淀、归档、importance/confidence、单一来源、部分 Trace |
| 可复用 | Memory 表、Service 入口、API 路径、Agent 运维资源页、Work 表单、Actor/AgentGrant、SSE 身份校验、参考消息规则、用量归因 |
| 需要调整 | User 所有权改为 Agent 所有权；通用及运维权限；正文覆盖改纠错；有界相关检索；类别权重；来源展示；流式写入可靠性和幂等 |
| 需要删除/停止使用 | 新写入允许 agent_id=NULL、运行时 NULL Agent 兜底、Memory 私有 owner 过滤、“仅当前账号可见”文案、无关记忆靠 importance 入选、原始提取输出日志；经批准迁移时清理无 Agent 脏数据 |
| 需要新增 | Kind/Subject/时间有效性/来源模式、Evidence/关系/演化事件/异常事项、自动治理、删除传播、详情与纠错冲突、统一 Trace、规模与并发测试 |
| 明确不做 | Shared Promotion、Personal/Workspace Memory 产品、Meeting 集成、完整 Experience、GraphRAG、新向量基础设施、自动 Work Executor、Monitor/Reminder、大型任务队列 |

## 11. 文档与代码差异

1. 历史及当前产品基线描述用户私有 Memory，准确反映 1.x；2.0 的共享仅是本次批准的目标，尚未在代码生效。
2. Memory ORM 注释未列 focus，API/Service 已支持；不能重做 focus。
3. “空间级记忆”是旧注释，不代表团队共享。
4. 其他 RAG 模块有 BM25/向量能力，不代表 Memory 已采用；本期不重构 Knowledge RAG。
5. expires_at/embedding 有列但未在 Memory 运行链生效；不能以列存在宣称能力完成。
6. “删除记忆”实际归档；事实变化仍缺独立状态和关系，不需要先把现有归档改成物理删除。

下一步以配套方案评审为准。方案确认前，不执行 ORM、数据库或正式业务开发。
