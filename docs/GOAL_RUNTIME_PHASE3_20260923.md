# Goal Runtime Phase 3 — 持久状态与有界执行

日期：2026-09-23。前置：[Phase 2](GOAL_RUNTIME_PHASE2_20260923.md)、[已批准数据库方案](GOAL_RUNTIME_DB_PROPOSAL_20260923.md)。本阶段新增独立、显式调用的 Goal API；普通 Conversation SSE、Proxy、@Agent 协作仍使用原路径。

## 执行路径

`GoalRequest → Deterministic Parser → GoalState → Runtime Reasoning → Action → Capability Executor → Observation → State Update → 下一轮或停止`。

- `runtime/state.py`：RUNNING / COMPLETE / BLOCKED / WAITING / FAILED，Action 的 started/completed/unknown 阶段，运行预算、参与者集合的预留字段和确定性停止原因。
- `runtime/loop.py`：复用 LangChain `astream` 和工具调用。一次模型响应既读取既有结果，又决定下一项工具行动或输出最终答案；不固定增加 Goal Enrichment、Planner、Evaluator 调用。缺乏明确目标时直接 ASK_USER。
- `runtime/bindings.py`：复用 Data、Web、Knowledge、Memory 执行器和 Phase 2 Observation Adapter。主 Agent 工具描述保持可用，知识/记忆作为可选择的检索能力；没有自动发现其他 Agent，没有把 Workspace Agent 目录装入 Prompt。
- `runtime/store.py`、`models.py`、`artifacts.py`：短事务检查点、所有者隔离、幂等键、revision CAS，以及私有不可变文件快照。
- `api/goals.py`：独立数据库 session 的 SSE，沿用 user_message/token/done/error 事件，并增加 goal_status。最终结果同时保存到原会话；取消时保留部分回复及停止状态。完成后复用 Post Runtime Cognition 注册，不占 Goal 执行预算。

没有要求新的 Reasoner 输出自定义完整规划 JSON。当前使用模型原生结构化 tool_calls；纯文本最终回答作为完成提议，经预算、工具 grounding、未解决失败和输出完整性检查后进入 COMPLETE。这不是独立语义验收器，不能证明任意复杂成功标准均已满足。

## API 与开关

仓库 `features.goal_execution_enabled` 默认 false。服务端开关开启后仍须显式调用下列新接口；旧 `/messages/stream` 不接管。

| 接口 | 行为 |
| --- | --- |
| POST `/api/conversations/{conversation_id}/goals/stream` | `{content, idempotency_key, budget?}` 创建并执行。新 Goal 返回 SSE；相同键与正文返回原状态，不重复调用。键已用于不同正文/会话返回 409。 |
| GET `/api/conversations/{conversation_id}/goals/{goal_id}` | 返回状态、revision、停止原因、下一动作、累计预算、结果消息 ID。 |
| GET `/api/conversations/{conversation_id}/goals/{goal_id}/result` | 返回已持久化的回复和来源，不返回内部 Prompt、输入快照或文件路径。 |
| POST `/api/conversations/{conversation_id}/goals/{goal_id}/resume` | `{content, revision}` 显式补参/继续同一 Goal。重读权限及上级策略，CAS 防止重复恢复；预算不重置。 |
| GET / PUT `/api/workspaces/{workspace_id}/runtime-policy` | workspace.manage 权限下查看/更新 `{budget: {...} 或 null}`，保留其他策略命名空间。 |

所有 Goal 接口继承 Conversation 当前 Workspace、owner 和 agent.use 校验，管理员也不会自动读取其他人的 Goal。代理主 Agent、@Agent 参与者、附件不在新入口当前支持范围；前两者返回明确的 409，未知请求字段由 Schema 拒绝。普通对话继续支持这些能力。本阶段没有新增前端开关或审批 UI。

完整目标、模型上下文、Action 结果、Observation/Evidence 存在 `data/runtime_goals/{服务器生成的Goal UUID}/{服务器生成的快照UUID}.json`，目录/文件权限 0700/0600，不挂载为静态文件。引用带 SHA256 和大小，每个快照最多 8 MiB；数据库 state 最多 64 KiB。Decimal、日期、UUID、bytes 保留显式类型标签及精确值；不会用任意 ORM 对象的字符串代替原始业务结果。Memory 快照保存实际传给模型的文本及来源信息，不复制 ORM/embedding。

## 自主边界和预算

执行前检查授权、预算并提交 Action started；外部执行期间不持数据库事务/行锁。完成后保存 Observation 再推进。只能执行本次已加载、仍获授权、低风险且无需确认的能力；LLM 无法通过发明工具名获得访问权限。工具缓存复用前仍重验授权。出现高风险/确认要求进入 WAITING + REQUEST_APPROVAL，当前阶段不接受自动批准或续跑。

Data 新入口在原 `_build_data_tools`/`execute_query` 上启用可选 `read_only=True`，复用 SQL draft 的语句校验，并设置数据库只读事务。旧调用默认 false，不改变成熟旧流程。主模型依据工具说明构造参数，复用确定性参数规则，不启动旧工具内部的额外参数解析模型调用。数据库结果保留原行、统计、参数和来源。

预算优先级：代码硬上限 → YAML runtime.budget → Workspace.runtime_policy.budget → Agent.quality_policy.runtime.budget → 请求 budget。每层取更小值，非法字段、负数、布尔伪装数值及超出硬上限的配置拒绝；无法通过请求扩容。恢复只进一步收紧已存限额。

| 预算 | 默认值 / 本阶段解释 |
| --- | --- |
| duration | 180 秒，跨恢复累计实际工作时间，等待用户时间不计；实时异步 timeout |
| llm_calls | 6，运行推理调用；禁用模型客户端自动重试 |
| tool_calls / tool_iterations / web_calls | 10 / 5 / 3；复用缓存不增加实际工具调用次数，仍消耗 Action 步数 |
| agent_calls / agent_depth | 0 / 0，Phase 4 前不开放 Goal Agent 调用 |
| context_tokens | 32000，以序列化上下文/Schema/说明 UTF-8 字节数加消息开销保守限制；超限停止，不截断结构或偷偷增加摘要模型调用 |
| output_tokens | 8192，跨轮累计输出文本/工具参数的保守字节计数，与 provider token 报告取较大值，并向 provider 传递剩余额度限制；它是安全预算估算，Usage 仍记录真实 provider token |
| max_steps / max_replans / max_failures | 24 / 1 / 2，重复失败不盲重试 |

模型读取上一轮实际 Observation 的 ToolMessage 原文进行下一次推理；缓存保留原始结果。NOT_READY → WAITING/ASK_USER；失败允许有限重判，不成功的相同参数结果也缓存，防止重复打外部接口。失败能力未被成功结果解决时不能静默变成 COMPLETE。无工具数据的业务回答被 grounding 检查拦截。

## 持久化、并发和中断

按已批准方案添加 nullable JSONB `t_workspaces.runtime_policy` 和 `t_runtime_goals`，含方案列出的 FK、CHECK、唯一约束和查询索引；没有新增 Action/Observation 明细表，没有 Backfill。Workspace 策略字段延迟加载以降低旧查询耦合；部署仍必须先迁移再发布新 ORM，不能依赖应用启动建表。

创建在同一事务验证会话所有者、空间、主 Agent 和新建初始消息归属。数据库唯一键保证同一 Workspace/owner/key 不重复创建。更新通过 owner/Workspace/conversation/revision 条件 CAS；失败时回滚消息与状态写入。文件先原子完成写入和 fsync，再提交数据库引用，失败遗留文件不被引用，暂不自动清理。

RUNNING 的检查点在最大运行时长 + 60 秒内不能被续跑抢占。超过窗口后，有权限的显式恢复请求只将中断标记为 WAITING；若 CAPABILITY started/unknown 无结果，禁止重放。取消模型调用可再次显式继续；取消未知外部行动必须人工核实。本阶段没有后台恢复调度器，不承诺外部 HTTP exactly-once。

Runtime Trace 复用既有 Debug，增加 `runtime_goal` 保护阶段，只记录枚举、计数和状态，不记录原始 Prompt/业务数据。实时/历史显示要求 agent.operate。Usage 复用既有 collector，`usage_detail.runtime` 记录 RUNTIME_REASONING purpose、goal_id、action_id。Model Profile/Gateway/Escalation 仍留在 Phase 6。

## 验证

- **400 passed**，零跳过；10 条警告均为既有 FastAPI on_event 弃用提示。
- 为本次测试启动了本机临时 PostgreSQL（127.0.0.1:55483），各集成测试使用独立随机 schema；默认业务 DATABASE_URL 强制指向不可连接端口。未向开发业务库写入测试 Goal/会话或调用付费模型。
- 全量测试包含新增 Loop/持久化/API/迁移，以及既有 SSE、Cancel、Partial Save、Memory Cognition、Usage、权限、协作、Proxy、知识、数据和工作模块回归。
- 新增场景包括正常 COMPLETE、缺参 WAITING/续跑、预算 BLOCKED、权限撤销时拒绝缓存、REQUEST_APPROVAL、工具结果未知、中断恢复拒绝重放、重复键和并发创建、过期 revision、私有读取隔离、文件完整性、Decimal 精度、真实数据库只读事务及 mutating function 拦截。
- 新模块 Ruff 和 git diff --check 通过。前端没有修改，沿用上一阶段构建产物。模型协议采用 mock/真实 LangChain mock HTTP transport 验证，未声称真实 provider 端到端验证。

## 部署与回滚

2026-09-23 23:01（Asia/Shanghai）部署到 `47.97.82.200`，重启 `agentdevstu.service`，状态 active/running、ExecMainStatus=0，启动完成日志正常。

备份目录：`/opt/agentdevstu/backups/goal-runtime-20260923-225552/`。包含 `application.tar.gz`（源代码与配置）、`database.dump`（完整 custom-format 数据库备份，1,005,346 字节）、`counts-before.json` 和 `migration-receipt.json`。首次调用系统 pg_dump 9.2 未成功，改用服务器已有 `/usr/pgsql-14/bin/pg_dump`，与 PostgreSQL 14.24 匹配；pg_restore -l 目录校验通过。备份目录 0700、数据库与应用备份 0600。

显式迁移事务成功，后续只读复核 installed=true/changed=false。Workspace、Agent、Conversation、ConversationMessage、Memory 行数均与备份前一致；Goal 表初始 0 行，Workspace 策略均 NULL，未回填历史数据。应用正常启动仍运行既有后台任务。

服务器仅合并 goal_execution_enabled=true，保留其余配置和 `.env`。Goal 创建/恢复以及 Workspace 策略路由在服务器 OpenAPI 冒烟中确认存在；预算继承冒烟通过。首页、`/chat`、`/login` 及四个入口 JS/CSS 返回 HTTP 200；原 Conversation、Goal 和 Workspace runtime-policy 接口未登录均返回 401。未向开发库写入测试 Goal，未执行真实模型端到端调用或浏览器渲染验证。仓库默认开关仍为 false，便于其他环境显式按迁移顺序启用。

优先回滚：关闭 goal_execution_enabled 并恢复备份应用代码；保留新增 schema 和 Goal 文件以免丢失检查点。物理删除表/字段需要另行批准。迁移脚本默认只读预检，显式 `--apply` 才执行；同名但定义不符时拒绝，不用 IF NOT EXISTS 掩盖结构差异。锁超时 3 秒、语句超时 30 秒，整个新增结构在短事务内完成。
