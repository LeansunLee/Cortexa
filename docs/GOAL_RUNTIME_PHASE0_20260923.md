# Goal Runtime — Phase 0 现状审计

日期：2026-09-23。代码基线：`36aaecf`。状态：**审计完成，数据库方案待确认；尚未实施 Phase 1–7。**

后续记录（2026-09-23）：用户回复“好的，继续”，已批准配套数据库方案。上述审计状态保留为 Phase 0 历史记录；当前实施进度见 [Phase 1 交付说明](GOAL_RUNTIME_PHASE1_20260923.md)。

## 审计范围与证据

- 依据用户本次完整任务、仓库 `Agents.md`、alpha v1.0.2609230000 基线、项目基线、架构说明、Memory 方案及当前实际 Python/Vue 实现。
- 全局检索 `invoke / ainvoke / astream / create_llm`、直接 HTTP 模型调用、预算与协作关键词，并追踪实际入口、执行器、权限中间件、后台认知和持久化代码。
- 通过开发库只读事务查询 `information_schema.columns`、`pg_constraint`、`pg_tables`，核对 Agent、Workspace、Conversation、Message、Collaboration、Usage 表；未读取业务正文或凭证数据。下文区分真实数据库类型与 ORM 声明。
- 未执行 DDL、Migration、ORM 修改、Backfill、业务数据写入、模型调用、服务启动或部署。本次只新增本文和[数据库方案](GOAL_RUNTIME_DB_PROPOSAL_20260923.md)。未运行测试；本文描述代码事实，不声称通过完整运行验证。
- `docs/ARCHITECTURE.md` 已注明其 LangGraph 架构是历史示例。当前 Web 对话入口不能按 researcher/writer/supervisor 图理解。旧基线中“Memory 待实现”等内容也不能作为当前事实。

## 1. Current Runtime Architecture（当前运行时架构）

### 1.1 SSE 真实调用链

入口：`frontend/src/views/Chat.vue` → `POST /api/conversations/{conv_id}/messages/stream` → `api/conversations.py:create_message_stream`。

```text
SecurityMiddleware（Session / CSRF / Actor）
  → authorize_request（Workspace / 会话所有者 / Agent 使用权 / 附件）
  → UsageMiddleware + usage_action("reply")
  → event_generator：独立 async_session_factory
  → 校验协作草稿 → 保存用户消息并 commit → user_message SSE
  → 获取主 Agent
      ├─ Proxy：本地输入解析 → execute_proxy_agent → 保存回复 → 登记记忆提取 → done
      └─ LLM：组织参考 / RetrievalPlan
          → 无原始 @ 提及时按计划检索 Knowledge（10s）/ Memory（5s）
          → 附件抽取
          → @Agent / collaboration_drafts 串行协作
              ├─ 传统纯 LLM @ 分支：目标回复直接组成最终答案
              └─ Proxy 或草稿分支：协作结果加入主 Agent 参考
          → 加载 DataCapability 工具 + Web 工具
          → system + references + 历史/摘要 + 协作参考 + 当前消息
          → _stream_model_response → LangChain astream
          → 最多 5 轮 Tool 调用 / 返回 ToolMessage / 再 astream
          → 保存助手消息、sources、steps、stats、debug_trace 并 commit
          → register_extraction（后台认知登记）→ done SSE
```

权限并非只依赖 API：`security/isolation.py` 通过 ORM 读写钩子传播 Actor 的 Workspace、所有者、Agent 授权约束。流式期间 `SecurityMiddleware` 每 2 秒检查授权变化，变化时取消任务。新 Runtime 和恢复入口必须继续使用这一链条。

取消时，若已有 `full_reply` 且未保存，使用 shield 和另一独立 session 保存 `stopped=True` 的部分回复；协作流通过 `aclosing(stream_handoff(...))` 清理目标任务。普通异常返回 error SSE，但并没有统一的 Goal FAILED 状态或通用部分结果恢复机制。

### 1.2 其他执行入口

| 入口 | 当前差异 / 兼容要求 |
| --- | --- |
| `create_message` | 非流式路径，拒绝非空协作草稿；在 async handler 中同步 `model.invoke`，另有工具循环；不能认为与 SSE 共用同一 Runtime |
| `regenerate_message` | 删除上一助手消息并通知 Memory 生命周期；重建上下文，调用 `invoke_with_tools`；该 helper 最多 4 次模型调用，最后一次移除工具并要求收尾 |
| `collaboration/manager.py:_execute_target_agent` | 使用目标 Agent 自己的模型、知识、记忆与数据能力；独立 DB session；再次实现工具循环 |
| `api/meetings.py` | 另有讨论、主持总结、结论和待办模型调用；保留现有入口，后续渐进委托 |
| `workflow/engine.py` | 固定 Workflow 节点执行，读取版本快照；不应被改成 @ 顺序语义 |
| `agents/agents.py` / `workflow/graph.py` | 早期 LangGraph / CLI 示例，有简单 goal 文本和迭代次数；不是 Web Goal Runtime |

### 1.3 Runtime Context、ContextBudget、RuntimeBudget

**当前没有可复用的统一 `RuntimeContext`、`ContextBudget`、`RuntimeBudget` 类，也未找到其完整等价实现。** `src/agentdevstu/runtime` 下没有实现文件。存在的是局部策略和计数，应先抽取它们，而非假定已有服务可直接调用。

| 现有控制 | 实际边界 |
| --- | --- |
| `limited_history` / `history_text` | 历史默认 18,000 字符，每条最多 4,000，长条保留头尾；不是 Token 预算 |
| `reference_message` | 序列化参考超过 12,000 字符时截断；不是结构化上下文投影 |
| SSE 历史摘要 | 查询最近 50 条再限长；超过 6 条尝试摘要，调用方 15s 超时；摘要函数还有自身短输入判断 |
| `prepare_background` | LLM 近期历史 14,000 字符预算，另加当前输入和附件；不是总输入预算 |
| `memory/retrieval.py` + `memory/policy.py` | 已有候选上限、相关性过滤、时间/冲突策略及保守字符 Token 估算；属于 Memory 专项预算 |
| Knowledge | 文档数量、全文窗口等常量上限，主对话调用 10s 超时 |
| Tool | SSE/协作各最多 5 轮，重新生成 helper 最多 4 次模型调用；轮数内工具个数没有统一总预算 |
| CollaborationLimits | 每请求 3 个 Agent、深度 2、默认超时 120s；Proxy 外层超时会按 HTTP timeout/retry 放大 |
| UsageTotals | 统计已返回模型 token，不预留额度、不拒绝超预算调用；不可当 RuntimeBudget |
| 模型 max_tokens | `create_llm` 读取 Provider 配置；调用方仅传 `agent.model`，Agent.temperature/max_tokens 并未自动覆盖 Provider 参数 |

缺少全请求 duration/llm_calls/tool_calls/web_calls/agent_calls、跨子调用共享预算、全模型输入 Token 约束及 max_steps/max_replans/max_failures。新增预算必须覆盖参数解析和后台认知调用；后台认知可单独分配明确的子预算，不能被漏算。

## 2. Current LLM Call Map（当前 LLM 调用地图）

`config/llm_providers.py:create_llm(name)` 的 `name` 实际是 `config.yaml` 的 Provider 配置键，具体 model 在该配置内。无参数时使用全局默认。Agent 创建时可继承 Workspace 默认，但每次调用并未统一动态读取 Workspace 默认。

统一 factory 已适配 OpenAI / Anthropic / Ollama，并绑定 `UsageCallback`。它还不是 Gateway：不要求 purpose，没有 profile、复杂度、风险、升级、跨 Provider fallback 或请求总 deadline。没有显式超时的调用依赖 SDK 行为；本次不把 SDK 默认值推断为 Runtime 硬限制。Provider `extra` 被读取，但当前构造函数没有统一透传。

表中“回调”指真实调用经 factory 的 UsageCallback 记录；“继承”指没有独立 purpose/action，只沿用外层 scope。工具自身 `ainvoke` 和 LangGraph `graph.invoke` 不重复计为模型调用。

| 调用位置 | 用途 | 模型选择 | 明确超时 | Usage 归因 |
| --- | --- | --- | --- | --- |
| `api/conversations.py:82`，1857/1954/1976 调用 | 主对话首答、工具后推理、最终输出，astream | 主 Agent.model | 无请求级 deadline | 回调 + reply + UsageTotals |
| 同文件 356/396/400 | 非流式首答、工具后回答、直接回答 | 主 Agent.model | 无统一 deadline | 回调 + reply + 局部统计 |
| 同文件 `_resolve_data_tool_args:616` | 有配置说明和参数时核对/修复工具入参 | 复用传入的主/目标/会议模型 | 60s | 回调，继承 action；未单独记 PARAMETER_REPAIR |
| `tools/web_search.py:245` | 重新生成等入口的工具推理 helper | 调用方传入 | 无统一 deadline | 回调 + 可选 UsageTotals |
| `collaboration/manager.py:456` | 目标 Agent 首答/工具后推理，委托共用 astream helper | 目标 Agent.model | 整个目标执行默认 120s | 回调 + target Agent 注解 + UsageTotals；非独立 purpose |
| `agents/proxy_input_resolver.py:209` | Prompt 模式整理上下文，启用后固定调用 | Proxy Agent.model | 解析器自身无；协作外层有 deadline | 回调，继承 action |
| 同文件 400 | 未解析的 context/infer 字段抽取 | Proxy Agent.model | 同上 | 回调，继承 action |
| `memory/service.py:168` | 早期对话摘要 / Context Compression | 调用方 model_name | 函数无；SSE 包裹 15s | memory_summary；标记 background 但当前可在响应关键路径执行 |
| 同文件 54 | 用户消息长期认知提取 | 当前 Agent.model | 30s | memory_extract，background |
| `memory/governance.py:174` | 确定性判断后有必要的语义治理 | 当前 Agent.model | 15s | memory_governance，background |
| `memory/integration.py:181` | 协作结果转为接收 Agent 的长期认知 | 发起/接收 Agent.model | 15s | 回调；没有独立 memory_extract scope，需补归因 |
| `rag/summary.py:60` | 文档上传后摘要；短文不调用 | 全局默认 | 60s | document_summary |
| `rag/multi_query.py:61` | 多查询改写 | 注入模型或全局默认 | 无显式 deadline | retrieval_rewrite |
| `rag/hyde.py:51` | 假设答案 | 注入模型或全局默认 | 无显式 deadline | retrieval_hyde |
| `rag/contextual_retrieval.py:73` | chunk 上下文前缀 | 注入模型或全局默认 | 无显式 deadline | retrieval_context |
| `api/meetings.py:426/451` | 会议发言与工具后推理 | 发言 Agent.model | 无统一 deadline | meeting_discussion + Agent 注解 |
| 同文件 494 | 主持人每轮总结 | 主持 Agent.model | 无统一 deadline | 继承 meeting_discussion |
| 同文件 721 / 757 | 最终会议结论 / 待办提取 | 全局默认 | 无统一 deadline | meeting_conclusion / meeting_todos |
| `workflow/engine.py:223` | 工作流 Agent 节点 | 当前代码直接使用全局默认 | 无统一 deadline | workflow_agent |
| `agents/agents.py:73/114/132` | 历史 researcher / writer / supervisor | `_get_model` → 全局默认 | 无统一 deadline | 真实模型有回调；factory 失败时本地示例 responder 不消耗 LLM |
| `api/schema_generation.py:99` | 数据能力 Schema 生成 | Workspace 默认或全局默认 | 45s | schema_generation |
| `api/sql_drafts.py:394` | SQL 参数化辅助 | Workspace 默认或全局默认 | 12s | sql_parameterize |
| `work/candidates.py:90` | 工作候选提取 | 来源 Agent.model | 40s | work_extract，background |
| `web/app.py:test_provider` | Provider 连接测试，直接 HTTP | 用户指定配置 | HTTP 30s | 手动 UsageCallback，provider_test |

另有 `rag/embedder.py` 的 Embedding 网络调用，由 `AuditedEmbeddingClient` 记录 embedding_query / embedding_index。不是上述文本推理 purpose，但需要保留统计，不应在 Gateway 改造时遗漏。

RAG 增强模块存在不等于每次 Conversation 使用：当前 `agents/knowledge.py` 主检索是确定性摘要匹配与全文窗口选择。不能为这些现成 helper 强加新模型调用。

**Usage 可复用性：**已有 operation/step/parent_step、来源、触发者、用户/空间/Agent、Provider kind、requested/actual model、Token 细项、耗时、状态、错误类型、重试计数、`usage_detail` JSON。SQLite outbox → PostgreSQL 幂等 upsert 可复用。新增 purpose/profile/complexity/risk/escalated/fallback/goal_id/action_id 可放 `usage_detail.runtime`，无需新增列；必须修改 callback 实际捕获这些键，不能只写 ContextVar 就假定已落库。重试统计当前仅 callback 可见，不保证覆盖 SDK 内部全部重试。

## 3. Current Collaboration Flow（当前协作流程）

1. `parse_mentions` 正则提取 `@名称`，保留出现顺序，`message_after` 为下个 @ 之前的任务文本；`fuzzy_match_agent` 使用名称/包含/固定别名。
2. 前端会把 @ 转为可编辑任务卡；`collaboration_drafts` 非 None 时覆盖后台提及列表。因此前端常用的是草稿协作路径，而非传统直接 @ 路径。
3. `validate_drafts` 要求依赖只能引用前面已出现的任务。Vue 发送校验、`moveDraftOrder` 也有同样限制。不存在与排列顺序解耦的依赖图调度。
4. `list_collaboration_agents` 查询 active + Workspace + 排除自身，HTTP Runtime 下还受 ORM Actor 授权过滤；随后匹配目标。不是自主 Discovery 排名，不会让模型选择全部 Workspace Agent。
5. SSE 对前 3 个 mention **逐个 await**。已有协作总数被读取，但未变成有效全 Goal 调用预算；`check_collaboration_limits` 当前总是返回 allowed=True。
6. 构造 Handoff → `stream_handoff`（任务/心跳/取消）→ `execute_handoff`（再次授权、深度检查、协作记录和超时）→ `_execute_target_agent`。
7. LLM 目标会拿自己的资源、近期主对话参考，且 `dependency_results` 当前包含全部前序协作结果，并不只含显式依赖。Proxy 外发与本地解析上下文另行处理。
8. 传统纯 LLM @ 可直接交付目标回复；有草稿或 Proxy 时一般交回主 Agent 汇总。这是近似 delegate/consult 的两种结果处理方式，**未找到显式 consult/delegate 模式枚举、策略或统一协议**，不应宣称已有完整模式体系。

当前没有三种 autonomy 模式的消费链、Goal 内 approved/denied 集合、ASK 多选授权 API/界面、Agent Top-K Discovery、共享 agent_calls 计数或通用调用栈循环检测。当前 depth 检查不能替代未来 A→B→A 的循环检测。

### Proxy 的已实现边界与缺口

- `proxy_config`、Agent input/output schema、字段 request/response mapping、HTTP timeout/retry、运行记录可直接复用。
- 结构化 resolver 已有 strict/context/infer、allowedSources、显式值优先、字段来源、置信度、JSON Schema 校验、blockingMissingFields/canInvoke。
- 默认外发基础路径并不复制主 Agent 完整 System Prompt、Memory 或 Knowledge。`prepare_background(target_type='proxy')` 返回无上下文；不要把这点误报成“现在所有 Proxy 都泄露完整 context”。
- 但本地 `prepare_proxy_resolution_context` 会读取最近 12 条对话与附件并字符截断；Prompt 模式默认允许 current_task、conversation_context、previous_agent_output，并固定调用 LLM 整理。结构化解析按来源收集 payload，缺少字段级最小投影和总 Token 预算。
- `execute_proxy_agent` 只有启用 resolver 的分支会经过上述校验；不能把已有 input_schema 当作所有外发路径已强制验证。没有统一 output_schema 校验。
- 现有 `requires_input/input_required` 可映射 Observation.NOT_READY，保留 missing_inputs；现在返回本轮缺参结果，没有可恢复 Goal Loop。
- 新路径需为外发和本地 LLM 解析分别执行 default-deny 投影。允许来源名称不等于允许其全部字段。超预算保留完整事实单位，丢弃不相关项或返回 NOT_READY，不能截断 JSON/关键事实冒充完整输入。

## 4. Reusable Components（可复用组件）

| 组件 | 复用方式 |
| --- | --- |
| `agents/retrieval.py:RetrievalPlan` | 确定性信号提取；当前 data/followup 等字段不代表已有完整路由器；Raw Goal 仍可直接合法 |
| `agents/knowledge.py` / 文件正文存储 | Knowledge Adapter 包装当前检索，保留来源和读取失败信息 |
| `memory/retrieval.py:RetrievalResult` | 包装 Memory Observation；保留时效、冲突、来源模式、引用证据及权限 |
| `memory/integration.py` | 回复持久化后登记提取，后台新 session 重验授权；当前是进程内任务 + 消息状态，不是耐久任务队列 |
| DataCapability + `_build_data_tools` | 保留 SQL 参数规则、Pydantic Schema、绑定、数据源凭证与实际 execute_query；Adapter 不重写 SQL 执行 |
| `bounded_result` / DataQuery | 保留 returned_rows、truncated、facets 与审计，Observation 不以 summary 替换原始证据 |
| `tools/runtime.py` | 业务数据必须真实工具支撑的首轮检查和失败保护 |
| `tools/web_search.py` | 绑定及用户禁止联网策略、真实搜索 HTTP、sources；搜索本身不是 LLM 调用 |
| Tool 表 / LangChain StructuredTool | name/description/input_schema/output_schema；Tool 表有记录不等于已有通用执行器，当前主对话实际执行 Data 与 Web |
| AgentHandoff / AgentHandoffResult | Agent Adapter 与 Observation 桥接，保留 result、sources、usage、input_snapshot；固定 confidence=0.85 不应当作校准置信度 |
| SecurityMiddleware / Actor / require_agent_use / ORM isolation | 启动、发现、执行、恢复和后台任务同样鉴权；显式 @ 不绕过权限 |
| `UsageCallback` / usage_scope / outbox | Gateway 复用已有计量与持久化；每次真实模型尝试记录一次 |
| `_debug` / debug_trace / SSE debug / Chat 调试抽屉 | 扩展 stage 与 detail，继续用同一套 Debug，不新建 Trace 平台 |

Agent 可复用字段：name/description/role/responsibilities/tags、input_schema/output_schema、knowledge_base_ids/tool_ids、model、memory_config、collaboration、quality_policy、permissions、proxy_config、status。后四类已有 JSON 列并不等于已有配置消费链：当前 AgentCreate/Update/Out 未公开 collaboration/quality_policy/permissions，版本 snapshot 也未包含它们，需要补 API/UI/版本处理。

Workspace 目前只有名称/描述、default_model_provider、system_prompt、status 和时间等字段；没有 Runtime policy/budget JSON。平台 Provider 及 feature flag 已在 YAML，可直接扩展 Model Profile，凭证继续留现有环境变量。

### Trace 与权限注意事项

`_debug` 记录本轮输入、参考、上下文、协作、工具、回答与 Usage，写入 Message.metadata_json 并通过 SSE 镜像。`_debug_safe` 仅对特定键和深度/长度脱敏，不能清除普通文本中夹带的所有敏感信息。

当前 debug 总开关没有统一的 Agent 配置查看权限校验；Memory trace 局部检查 agent.operate，历史读取对普通用户主要去掉 memory stage；协作 `visible_snapshot` 有 agent.read 控制。新 Goal Trace 需要在 SSE 和历史读取两端统一投影，尤其不能把完整主 System Prompt 或未授权候选信息直接送给所有 agent.use 用户。

## 5. Required Changes（必要改动）

按阶段 Extract → Delegate → Verify；每阶段独立验收，不把下列清单一次性实现。

| 阶段 | 最小交付 | 验收与旧路径保护 |
| --- | --- | --- |
| Phase 1 | 纯领域 Goal/Gap/来源模型；确定性 Normalize/信号解析/Router；shadow flag；复用 Debug | 不调新 LLM、不执行新 Capability、不改 @ 顺序、不影响 SSE 内容和认知；Parser 失败可记录后继续旧路径 |
| Phase 2 | Descriptor/Matcher/Observation + Data/Web/Knowledge/Memory/Agent Adapter | 不建 Capability 表；保留原始结果和 Evidence；Matcher 的新 Discovery 规则不能直接改坏现有 Data 全量绑定测试 |
| Phase 3 | 抽取统一 Context/Budget；结构化一次 Reasoning；Goal State/Action/Loop；新路径 flag | 同一次调用可评价前次结果并决定下一步；先落共享预算再允许自主调用；BLOCKED 明确 ASK_USER/REQUEST_APPROVAL/RETRY/REPLAN/FAIL |
| Phase 4 | @ 变为参与者；动态依赖；EXPLICIT_ONLY/ASK/AUTONOMOUS；确定性 Top-K；授权多选 UI | 同 Goal 拒绝不再问；批准不重复问；每次执行仍重验实时权限；并行子任务各自 session、共享预算原子预留 |
| Phase 5 | Invocation Builder / Projector / 强制输入与输出校验 / NOT_READY | 从现有 resolver 提取、委托执行器；仅显式允许字段，保留来源与预算证据；新旧 Proxy 路径由 flag 控制 |
| Phase 6 | Gateway purpose、profiles、LIGHT/STANDARD/COMPLEX、逐调用路由、升级/fallback | 复用 factory 和 callback；读取剩余预算；配置缺失可兼容现有模型；流式已输出后不得透明重放重复答案/工具 |
| Phase 7 | Trace 脱敏/权限收口、Token 与性能对比、完整回归、文档/部署 | shadow 与 baseline 对比；再有限开启 Goal 执行；保留一键返回旧路径 |

Phase 3 如需新 Runtime Reasoning，可先经最小 purpose-aware 调用包装委托现有 factory；完整动态 Model Router 到 Phase 6 再实施，避免在过渡期新增另一套无记录模型调用。

**测试计划（尚未执行）：**

- Phase 1：简单请求无额外 LLM；确定性解析及字段来源；Gap 分类；仅 SEMANTIC_GAP 可申请 enrichment，Shadow 下始终不调用；flag 开关不改变原回复。
- Phase 3：COMPLETE、预算耗尽、BLOCKED 不盲循环、WAITING 恢复、max_steps/replans/failures、子 Agent 共享消耗、取消与幂等重试。
- Phase 4：@排列变化不强制顺序；EXPLICIT_ONLY 不发现未指定 Agent；ASK 多候选勾选；批准/拒绝跨轮仍有效；AUTONOMOUS 限 Workspace、授权、availability；深度/调用次数/A→B→A 检测。
- Phase 5：完整 Context 不外发；输入/输出契约、缺参 NOT_READY、字段 allowlist、输入预算、Observation 返回 Loop。
- Phase 6：FAST/BALANCED/REASONING 按目的路由、升级、Provider/Model fallback、每次尝试 usage/purpose、预算不足的 Finalization。
- 回归现有 `test_conversation_streaming/commit/debug`、`test_collaboration*`、`test_proxy*`、`test_retrieval_policy`、`test_web_search`、`test_model_usage/usage_totals`、`test_memory2`、`test_identity_security`；新增完整 SSE cancel/partial-save 与恢复鉴权覆盖。部分现有集成测试会写数据库，必须用隔离测试库，不能直接跑到开发业务库。

## 6. Potential DB Changes（潜在数据库改动）

Phase 1–2 可以纯内存模型、现有 JSON 与 feature flag 实现，不需要 DDL。Agent 自主策略、Proxy 契约、Usage metadata 也可复用既有列。

完整方案建议在 Phase 3/4 采用 **Workspace 新增一个 runtime_policy JSONB 列 + 一张 t_runtime_goals 状态表**，承载结构化空间硬约束、独立 Goal 生命周期、授权集合、预算快照和并发修订。不是为了 Parser 或统一 Capability 增表，也不是重建日志系统。

仅复用 Conversation.metadata_json 并加行锁也能实现缩减版本，但会把多个 Goal、授权恢复、摘要等状态耦合在同一大对象中；Workspace 策略还需另存 YAML。它是可选的零 DDL 路线，不应被说成技术上不可能。推荐方案、具体字段、约束、兼容、迁移、风险与回滚见[数据库方案](GOAL_RUNTIME_DB_PROPOSAL_20260923.md)。

**STOP：推荐的完整方案涉及数据库结构。按本次任务第 6 条，在此等待确认；不提前修改 ORM、不执行 Migration/DDL/Backfill、不开始 Phase 1 实现。**
