# Goal Runtime Phase 4：目标协作

日期：2026-09-24。延续 [Phase 3](GOAL_RUNTIME_PHASE3_20260923.md)，本阶段只接入 LLM Agent 协作。Proxy Input Contract/Gateway 分别留在 Phase 5/6。没有数据库 DDL、迁移或历史数据回填，复用 Agent.collaboration、Workspace.runtime_policy、Goal.state JSON 和现有协作审计表。

## 用户行为

聊天页在服务端启用且主 Agent 为 LLM 时提供「目标模式 / 普通对话」，默认目标模式。普通对话继续走原 Conversation SSE，Proxy 主 Agent 保持普通对话。目标模式暂不接收附件，普通对话继续支持。

目标模式中的 @Agent 表示授权参与者，不表示静态执行顺序。卡片不显示序号、提前/延后按钮，分工可选；模型根据任务与真实结果选择下一步。普通对话保留旧任务卡行为。用户明确说「只找销售Agent」同样解析为显式参与者；「不要找其他 Agent」「禁止协作」持续收紧整个目标，包括后续补充。

Agent 编辑页的模型配置提供三档目标协作权限：

- EXPLICIT_ONLY（默认）：仅允许用户明确指定的参与者。
- ASK_BEFORE_COLLABORATION：找到相关 Agent 后，在实际选择协作时暂停；用户可多选批准，未选者拒绝。默认没有勾选，不自动代用户授权。
- AUTONOMOUS：可在当前用户权限、空间策略、目标约束和预算内自主选择。

目标批准/拒绝只属于当前 Goal。拒绝者不再次推荐或请求；改变拒绝需新目标。授权请求要求完整分配全部候选，拒绝注入候选外 ID；revision CAS 防并发覆盖，同一决定重提幂等。恢复保留预算和历史授权。聊天页支持刷新状态、恢复已保存的目标和显式新目标；结果未知的外部行动不能自动重放。

Agent 同时可设置 allow_incoming、discoverable；协作配置保留旧 consult/delegate 键，保存后按既有草稿/发布流程生效，版本快照包含协作配置。

## 策略、发现与执行

平台 `runtime.collaboration` 和 Workspace `runtime_policy.collaboration` 支持 enabled、max_autonomy、candidate_limit，只能收紧 Agent 配置。Workspace 策略 PUT 保留未提交的预算/其他命名空间，仍要求 workspace.manage。每次执行和缓存访问重新检查权限；源权限收紧后，旧批准也不能扩大权限。

先筛当前 Workspace、用户 Agent 使用授权、active 状态、可协作性与目标约束，再用 Phase 2 确定性 Matcher 对名称/描述/aliases/operations 排序。发现候选默认最多 3、配置上限 5；仅显式/已批准参与者及少量相关候选进入模型。完整 Agent 目录不进入 Prompt，没有新增 Planner/Discovery LLM 调用。

Agent Capability 调用现有 GoalLoop。子 Agent 只收到自己的系统配置、本次委托、契约 inputs，以及主模型按真实 action_id 选出的成功 Observation；不存在/未完成引用不执行。不会发送主 Agent 的系统 Prompt、完整聊天历史、全部记忆。输入按保守字节预算检查，不用额外摘要模型；LLM 输入/输出 schema 作基本本地校验，禁止远程 JSON Schema 引用。Proxy 参与者明确拒绝并提示普通对话，严格 Proxy 投影留待 Phase 5。

子 Agent 的 Data/Knowledge/Memory/Web 使用既有成熟适配器。结果转换为统一 Observation 回到主推理；数据源与协作授权来源 USER_EXPLICIT / USER_APPROVED / RUNTIME_AUTONOMOUS 随结果保留。主模型得到真实 observation_id 后才能传给其他参与者，不能靠 @ 文本次序隐式传递完整上下文。

主子 Agent 共享同一目标的 LLM、工具、Web、输出、步骤、失败/重判预算。子任务发起前预占主预算，取消与失败后已用成本不返还；真实 provider Usage 合并到主统计，collector 仍保留目标/行动/目标 Agent 归属。agent_calls 默认 3，agent_depth 默认 1；每层仍只能收紧默认预算（配置可取值上限 5/2 不表示能扩大默认值）。本阶段只向主 Loop 注册 Agent 能力，实际最多一层委托；循环与深度检查在调用边界执行。禁用 SDK 自动重试，沿用 120 秒协作超时及主目标剩余时长。

## 持久化与 API

没有增加表或列。Goal 检查点保存显式/候选/批准/拒绝/已用参与者、活动子行动及决定指纹。子 GoalState、模型消息、Observation 和完整协作输出写入私有 Goal 文件快照；DB 的协作卡片只存摘要和 action 引用，展开时经会话所有者校验读取完整输出。既有 Conversation 最终答复保存方式不变。协作审计仅保存摘要、有限结果前缀及目标/行动/授权来源。

新增接口（均在既有 /api 下）：

| 接口 | 行为 |
| --- | --- |
| GET /conversations/{id}/goal-options | 当前会话是否支持目标模式 |
| GET /conversations/{id}/goals/{goal}/candidates | 本目标待批准且仍可用的候选 |
| POST /conversations/{id}/goals/{goal}/authorization | revision + approved_agents + denied_agents，记录决定 |
| GET /conversations/{id}/goals/{goal}/collaborations/{action} | 从私有快照读取指定协作完整输出 |

原 Goal 创建支持 participants（agent_id、可选 task，最多 5）；幂等请求指纹包括参与者分工。原恢复接口支持 collaboration_authorized。状态接口增加 pending_agents 与 recovery_allowed；中断超期的恢复先标记状态，未知外部行动仍拒绝再次执行。开启新能力使用 `features.goal_collaboration_enabled`；仓库默认 false，开发服务器部署后设 true。

## 验证和部署记录

模型决策通过 scripted LangChain 流验证，不声称真实模型提供商端到端成功；数据库集成使用本机临时 PostgreSQL 随机 schema，不向开发库注入测试会话或业务结果。浏览器使用真实构建产物与隔离 API 响应。

部署前全量与部署后检查结果见本节末尾的发布记录。回滚优先关闭 goal_collaboration_enabled 并恢复备份代码/前端；保持 Phase 3 数据结构及 Goal 私有文件，不删除新产生的目标记录。无需数据库回滚。

### 发布结果

- 后端最终全量 **414 passed**（45.04 秒，零跳过），10 条均为既有 FastAPI on_event 弃用警告；新增 14 个用例/参数化场景。另对 Goal 协作、持久化、Loop 做过 35 项定向回归。
- 前端 Node **42 passed**，构建通过。修复既有协作输出测试的 Vue 头像组件导入夹具，使其继续验证完整长文本及 HTML 转义；没有修改该断言。构建仍有既有大 chunk 提示。
- 新增 `frontend/tests/goal-collaboration.browser.cjs` 验证无序且分工可选的参与者、多选授权与拒绝、原目标续跑、刷新恢复、私有快照完整输出、普通对话切换、浅色/深色/窄屏。分别对本地构建和开发服务器实际静态资源通过；API 为隔离响应，不是付费模型实调用。
- 新增 `tests/test_goal_collaboration.py` 验证策略收紧、权限和 Workspace 隔离、提及次序不决定调用、共享 LLM/工具/Agent 预算、输入缺失、循环/深度、ASK 完整分配和幂等、拒绝持久化、AUTONOMOUS 授权来源、子上下文隔离、取消后禁止重放、配置合并/版本快照、完整输出文件读取。其余原 SSE/Proxy/Memory/权限回归均通过。
- 新 Runtime/API 模块 Ruff 与 `git diff --check` 通过。开发服务器 staging 导入预检成功，现有依赖满足要求，没有安装或升级服务端依赖。

已于 **2026-09-24 08 时段（Asia/Shanghai）**发布到 `47.97.82.200`。备份 `/opt/agentdevstu/backups/goal-runtime-phase4-20260924-0805/application.tar.gz` 已通过 tar 目录验证，包含更新前代码、前端和 config.yaml；目录 0700、备份 0600。发布文件哈希清单位于同目录 `deployed-hashes.json`；HTTP 检查回执为 `http-receipt.json`。

只合并服务器 `features.goal_collaboration_enabled=true`，保留 `goal_execution_enabled=true` 与其余配置；`.env` 未变。重启 `agentdevstu.service` 后 ActiveState=active、SubState=running、ExecMainStatus=0，启动完成日志正常。新路由和功能开关在运行环境中复核通过。首页、`/chat`、`/agents`、`/login` 为 200；目标选项/候选/私有输出接口匿名为 401；入口 JS/CSS、Chat JS/CSS、Agents JS 的 HTTP 内容 SHA256 与本地构建一致。

没有执行数据库结构变更或在开发库创建测试 Goal；本机临时 PostgreSQL 验证完成后停止。当前修改保留在工作区，未自动创建 Git commit。
