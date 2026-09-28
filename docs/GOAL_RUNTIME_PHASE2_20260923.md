# Goal Runtime Phase 2 — Capability 与 Observation

日期：2026-09-23。前置：[Phase 1](GOAL_RUNTIME_PHASE1_20260923.md)。本阶段继续 Shadow Mode，不修改数据库结构，不增加模型调用。

## 实现

- `runtime/capabilities.py`：统一 Tool、Data、Knowledge、Memory、Web、Agent 描述，预留 Human/Robot/Sensor 类型但禁止当前 Matcher 选择。描述包含输入/输出 Schema、能力范围、可用性、权限重校验要求、风险、确认要求、上下文策略、输入预算和超时。未知限制保留为空，不伪造已实施的安全策略。
- Matcher 先过滤 Workspace、服务端提供的 allowed_ids、可用性和类型，再按名称、别名、领域、描述和操作进行确定性匹配；最多返回 20 个候选，相同分数按 ID 排序。中文使用 bigram，查询和描述词元处理有界；不增加 LLM 调用。
- `runtime/observations.py`：统一 source_type/source_id/action_id/status/summary/facts/evidence/confidence/error/metadata/occurred_at。状态区分 SUCCESS、EMPTY、PARTIAL、NOT_READY、FAILED、TIMEOUT、UNKNOWN。
- `runtime/adapters.py`：对现有执行器的结果做适配，不重新执行、不重新授权。Data 保留原始行、行数、截断、统计 facets 和实际参数；Web 保留来源摘要；Knowledge 保留来源和处理中/不可读信息；Memory 保留来源类型、置信度及冲突标记；Agent 保留原始输出、来源、Usage 和输入快照。`raw_result` 引用完整原始对象，调用侧原有结果不被改写。
- 原始记忆和网页摘要不升级为已验证事实；旧 Agent 返回的 confidence 标记为 `legacy_unvalidated`。未知文本结果保持 UNKNOWN，不把提示文案误判为成功；Proxy 缺参映射为 NOT_READY，并保留 missing_inputs。

## 接入与权限

Conversation SSE 的直接 Proxy、Knowledge/Memory 检索、Agent handoff、依赖失败跳过、Data/Web 工具结果和异常接入适配。缓存命中仍保留一次 Observation，并标记 reused_cache；沿用原来的工具去重、ToolMessage 内容和异常传播。Knowledge 模块仅在既有可选 stats 中补充 pending_count/unreadable_count，不改变检索正文。

Matcher 当前仅观察本次已经加载的工具，不枚举 Workspace Agent，不改变模型绑定的工具列表。MatchScope 必须由服务端授权结果构造，不能把客户端传入 allowed_ids 当作授权。Descriptor 是当前执行器的描述；真正执行仍受原模块权限、Schema、上下文和限额检查约束。自主发现和严格 Proxy 投影分别在后续阶段实施。

`runtime/capture.py` 将元信息加入现有 Debug Trace：`runtime_capability`、`runtime_observation`。每次请求最多 64 条，加一条汇总遗漏数；达到上限后不再执行结果适配。Trace 只保存哈希 ID、类型、状态、数量及缓存/跳过标记，不复制原始结果、Schema、上下文、异常正文或凭证。完整 Observation 当前仅在进程内生成，后续 Goal Loop 可复用适配接口；尚不持久化完整 Observation 或 Action。

新 Trace 的实时 SSE、done 和历史接口统一要求 `agent.operate`；实时输出还要求现有 Debug 开关开启。适配失败只记录固定错误码，继续原流程。控制开关为 `features.capability_shadow_enabled`，只有 YAML 布尔 true 启用；关闭后跳过适配和匹配。与 Goal Shadow 开关独立。

## 验证

- 相关回归集：**189 passed，1 skipped**。跳过项为未提供隔离数据库的 Usage PostgreSQL 集成测试；10 条提示为既有 FastAPI on_event 弃用警告。
- 测试强制使用本机不可连接的数据库地址，外部模型和业务调用使用 mock，没有向开发数据库写入测试数据。
- 覆盖六类结果保真、状态映射、Schema 与敏感字段隔离、匹配权限/Workspace/可用性过滤、上限及适配失败、实时/历史 Trace 权限。
- SSE 回归覆盖 Shadow 开关、相同模型调用次数和 ToolMessage、工具缓存去重、检索来源、直接 Proxy 缺参、协作及依赖跳过；同时运行既有 SSE/取消/部分保存、Proxy 契约、协作、Usage、Memory 等相关测试。
- 新 Runtime 模块及新测试 Ruff 检查通过，`git diff --check` 通过。未修改前端，本阶段沿用 Phase 1 已构建的前端产物。

## 阶段边界与回滚

当前集成范围是 Conversation SSE 主路径及其 handoff 返回值；目标 Agent 内部工具循环、非流式和重新生成入口尚未接入。没有新增 Goal Loop、真实 Action 调度、自主协作或 Model Router。没有改变 @Agent 现有执行顺序。

关闭 capability_shadow_enabled 可立即停用本阶段影子采集，历史记录仍按权限过滤。回滚代码需恢复部署备份中的 conversations.py、knowledge.py、runtime 目录和配置；无需数据库 downgrade。

## 部署记录

2026-09-23 17:22（Asia/Shanghai）已部署到开发服务器并重启 `agentdevstu.service`，状态 active/running、ExecMainStatus=0，启动完成日志正常。服务器 Runtime 导入、PARTIAL 结果适配及 Trace 冒烟通过，两个 Shadow 开关均启用。只合并本阶段 feature flag，未覆盖其他服务器配置或 `.env`。

首页、`/chat`、`/login` HTTP 200，入口引用的四个 JS/CSS 资源 HTTP 200；未登录 `/api/conversations` 返回 401。本次是 HTTP/服务验证，没有执行真实模型端到端调用或浏览器渲染验证。

部署前核对服务器 Phase 1 文件哈希，备份为 `/opt/agentdevstu/backups/capability-shadow-20260923-172122.tar.gz`，包含原 conversations.py、knowledge.py、runtime 目录及 config.yaml。没有执行 Migration、DDL 或 Backfill；服务启动仍运行原有后台任务。
