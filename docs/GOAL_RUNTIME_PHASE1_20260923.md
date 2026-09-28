# Goal Runtime Phase 1 — 确定性解析与 Shadow Trace

日期：2026-09-23。前置：[现状审计](GOAL_RUNTIME_PHASE0_20260923.md)、[已批准数据库方案](GOAL_RUNTIME_DB_PROPOSAL_20260923.md)。本阶段不使用新表，不修改数据库结构，不接管旧 Runtime。

## 实现

- `runtime/goals.py`：NormalizedGoal、FieldSource、GapType、CollaborationConstraint、GoalRoute；Raw Request 保留，规范化换行和边缘空白，不把推断改写成用户目标。
- 显式标签 `目标：/对象：/约束：/成功标准：/输出：` 提取用户要求；整段 JSON 或明确传入的结构化值作为 inputs。普通自然语言没有明确字段时保留 raw objective，不编造 target、成功标准或参数。
- 操作关键词属于 DETERMINISTIC 信号；原文标签/参数/参与者/限制属于 EXPLICIT；未填写字段属于 DEFAULT；本阶段没有 INFERRED 值。
- 复用 `parse_mentions` 和 `plan_retrieval`。Goal 中参与者按引用规范排序，不携带顺序执行语义；旧协作执行仍使用旧路径。name 与 id 可能指向同一个 Agent，本阶段不查询目录消歧，Trace 计数是引用数量。
- 识别“不要找其他Agent”“只找销售Agent”“不要协作”等明确限制，仅作为解析结果。`allow_discovery` 是用户文本是否禁止发现的信号，不是调用授权。
- Gap Analyzer 接受明确缺失的结构化必填字段；模糊“处理一下”为 SEMANTIC_GAP；超长输入记录 INFORMATION_GAP。没有目录/环境证据时不臆造 Capability 或 Environment 不可用。
- Router 输出建议，参数缺口优先 ASK_USER、信息缺口检索、能力缺口解析、环境缺口检查；只有纯 SEMANTIC_GAP 标记 enrichment_eligible。本阶段所有 enrichment 都不执行，`llm_calls_added=0`。
- `runtime/shadow.py` 把有界解析信息写入现有 `debug_trace` 的 `stage=goal`。原文通过 message_id/hash 关联；不复制目标正文、对象、输入字段名/值、参与者名称或 schema 进入新 Trace。

## 接入与可见性

SSE 创建用户消息的同一事务内保存 Shadow Trace，因此模型失败或尚无输出就取消也保留原始解析记录。正常/Proxy/传统协作/草稿协作/部分保存路径的助手 debug_trace 都包含该条目。没有新增查询或独立写入事务，后续 Memory 登记仍合并原 metadata。

控制开关：`config.yaml → features.goal_shadow_enabled`，只有 YAML 布尔 true 启用，缺失/非法配置关闭。仓库配置启用 Shadow。`conversation_debug_enabled` 仍控制实时 Debug 输出；Shadow 存储不依赖它。

新 Goal Trace 的 SSE 单条事件、done payload、历史消息接口均要求 `agent.operate`。普通用户仍获得原有答案、状态、Usage 和来源。未增加 UI 页面，复用现有聊天调试抽屉；查看实时条目仍需现有 Debug 功能开启及对应配置页权限。

解析异常只记录固定错误码，继续旧链路；不写异常中的用户输入。解析工作量限制为 64,000 字符，超限保留完整 Raw Goal、标记 analysis_complete=false，不截断文本后冒充完整解析。

## 验证

- 相关回归集：160 passed，1 skipped（Usage PostgreSQL 集成测试未配置隔离库）。数据库 URL 强制设为本机不可连接端口，外部模型/业务接口使用 mock；未把测试数据写入开发库。
- 覆盖 Shadow 开/关的相同模型输入和调用次数、LLM/Proxy 回复、Debug 权限、历史过滤、解析失败、取消与部分保存，以及原协作草稿、依赖、Proxy 契约、知识/数据/联网、Usage 和 Memory 类型测试。
- 新模块/测试 Ruff 检查通过；前端 `npm run build` 通过。现有 FastAPI on_event 弃用提示和前端大 chunk 提示不影响本次验证。
- 本地同一短请求 500 次纯解析与 Trace 组装，中位数 0.030ms、P95 0.033ms；不包含 YAML 读取/数据库/网络，不能当线上请求延迟指标。

## 阶段边界和回滚

部署记录：2026-09-23 11:05（Asia/Shanghai）已 rsync 到开发服务器并重启 `agentdevstu.service`，服务为 active/running，启动日志正常。服务器解析冒烟通过，Shadow 开关已开启；只合并该 feature flag，保留服务器其他配置和环境变量。首页、`/chat`、`/login` 及入口静态资源 HTTP 200，未登录 `/api/conversations` 返回 401。浏览器自动化连接超时，未声称完成浏览器渲染或真实模型端到端验证。

部署前备份：`/opt/agentdevstu/backups/goal-shadow-20260923-110453.tar.gz`。本阶段没有数据库 schema 变更；正常服务启动仍会执行其既有 Usage/知识后台任务。

本阶段仅接入 Conversation SSE；非流式/重新生成暂保留原路径。Capability Descriptor/Adapter、真实 Goal Loop、ASK 授权、自主 Discovery、严格 Proxy 投影、Model Router 在 Phase 2–6 逐步实施。当前关键词规则只提取保守信号，不承诺理解任意复杂自然语言。

关闭 `goal_shadow_enabled` 后，新请求完全跳过解析；历史 Trace 仍按权限可读。不需要数据库 downgrade。若回滚代码，恢复部署备份中的 conversations.py 和 feature 配置即可；新增 runtime 模块可保留，旧入口不会调用它。
