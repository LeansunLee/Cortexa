# Goal Runtime Phase 5：Proxy 输入契约与上下文隔离

日期：2026-09-24。延续 [Phase 4](GOAL_RUNTIME_PHASE4_20260924.md)，本阶段让经过显式配置和发布的 Proxy Agent 作为 Goal Agent Capability 使用。没有新增或修改数据库表、列、索引，也没有数据回填；配置复用 `Agent.proxy_config` JSON，运行态复用 Goal 私有文件快照和现有协作审计表。

## 使用方式

Proxy 编辑页新增「目标模式输入契约」。管理员必须先声明静态 object Input Schema，再为每个字段选择允许来源：

- `explicit`：用户在聊天参与者卡片中填写的 JSON 参数；
- `goal_task`：该 Proxy 的明确分工，未填写时使用目标原文；
- `observation_facts`：主模型引用的已完成 Observation 结构化事实及 JSON Pointer；
- `observation_summary`：主模型引用的已有 Observation 摘要，不允许继续取子路径。

开关默认关闭。启用后还要保留 `allow_incoming`；自主发现另需 `discoverable`，并继续受 EXPLICIT_ONLY / ASK / AUTONOMOUS、用户权限、Workspace、目标约束和全局预算限制。配置保存进入草稿，按既有发布流程生效。动态引用、组合条件、未声明类型和没有 properties 的 Schema 不能用于目标模式，仍可走普通对话兼容路径。

聊天目标模式的 Proxy 参与者卡支持可选分工和「显式参数」JSON。前端只做对象与 JSON 语法校验；服务端始终重新按 Schema、字段来源和大小预算校验。继续原 Goal 时可补参与者参数，不重置消费预算、授权决定或 Observation。

## 默认拒绝投影

调用链为：Action → Agent Capability → Invocation Builder → Context Projector → Input Validator → 单次 Proxy Transport → Output Adapter → Observation。

Invocation Builder 不接受模型直接提交 `task`、`inputs` 或上下文正文；模型只能提交字段到 Observation 的结构化绑定。Runtime 按字段白名单组合显式参数、目标任务和指定 Observation。嵌套对象只保留 Schema 声明的 properties，额外键被拒绝；类型不自动转换，缺失或错误字段返回 NOT_READY。

以下内容始终不进入目标 Proxy 请求：完整 Conversation、完整 Memory、完整 Knowledge、其他 Agent 原始上下文、主 Agent System Prompt、Proxy headers 和凭据。目标执行不调用普通 Proxy 的 prompt/input resolver，不用 LLM 猜值或压缩。结构化投影删除未获准字段；若最终请求超过预算，完整结构停止执行，不做破坏语义的字符串截断。

输入预算默认 4000、范围 256–8000，使用序列化最终 HTTP body 的 UTF-8 字节上界并计入映射后的固定字段；同时受 Goal context budget 收紧。外部响应默认最多 128000 字节，可配置 1024–1048576。远程 JSON Schema 引用被禁止，校验不会访问网络。

缺少只允许显式来源的字段时，Goal 进入 WAITING，用户在原 Goal 补参数后续跑。缺少可由 Observation 补齐的字段时，Runtime 可消费一次既有 `max_replans` 预算，先调用其他能力取得事实，再引用真实 action_id 调用 Proxy。不存在、未完成、失败或路径无效的 Observation 不提供数据。

## 外部调用与结果

目标模式复用成熟 Proxy 的 Endpoint、GET/POST、环境变量 Header、request/response mapping 和 JSON/SSE/纯文本解析。每个 Action 只发起一次 HTTP 请求；忽略普通路径的 retry 配置。超时、取消、连接异常和不完整 SSE 均视为外部结果未知，Action 标记 unknown，恢复接口禁止自动重放。

响应先做大小限制与 mapping，再按 Output Schema 校验。外部 `not_ready/input_required` 转为 NOT_READY；明确失败或输出不符合契约转为 FAILED；失败结果不能被主模型静默合成为 COMPLETE。成功结果转换为 Agent Observation，结构化事实回到 Goal Loop。

外发的投影输入、最终 request body、响应和校验状态保存在私有 Goal 文件快照。数据库协作审计只存状态、摘要、时长及 Goal/Action/授权来源，不存完整请求、响应或 Header。对话消息沿用 Phase 4 的摘要和私有结果引用。

Debug Trace 只记录选择的字段名与来源、拒绝字段数量、固定的 denied-context 类别、是否发生结构化投影、输入预算上界和契约校验状态；不记录字段值、Prompt、Header、Endpoint、凭据或远程错误正文。授权来源仍区分 USER_EXPLICIT、USER_APPROVED、RUNTIME_AUTONOMOUS。

## Feature Flag 与兼容性

新增 `features.goal_proxy_enabled`，仓库默认 false。它和 `goal_execution_enabled`、`goal_collaboration_enabled` 必须同时开启，且单个 Proxy 的 `goal_contract.enabled=true` 后，才会进入目标候选。普通 Conversation SSE、Proxy 主 Agent、旧 consult/delegate、prompt/input resolver、补充提示词和旧 retry 行为保持不变。

Phase 6 的 LLM Gateway、Purpose Router、模型升级和 Provider fallback 尚未接入。本阶段没有真实外部生产 Proxy 或付费模型调用；端到端使用本地 mock HTTP transport 和 scripted LangChain 模型验证。

## 验证与发布

发布前验证覆盖：默认拒绝、嵌套额外字段过滤、类型不转换、显式参数、目标任务、事实与摘要引用、未知/失败 Observation 拒绝、最终请求预算、动态 Schema 拒绝、普通 resolver 不调用、response mapping、Output Schema、NOT_READY 补参续跑、先取 Observation 再调用、无外部自动重试、取消/超时未知结果和数据库摘要审计。

最终后端全量 **429 passed**（52.15 秒，零跳过），10 条均为既有 FastAPI `on_event` 弃用警告；Phase 5 新增 15 项定向测试。前端 Node **42 passed**，生产构建通过，保留既有大 chunk 提示。Phase 4 浏览器回归与新增 Proxy 浏览器验收均通过；浏览器使用真实构建产物和隔离 API 响应，验证了契约配置、可选分工、显式 JSON 错误拦截和参与者参数提交。

Ruff（新增 Runtime、Proxy transport、Goal API 和新增测试）与 `git diff --check` 通过。测试使用本机临时 PostgreSQL 随机 schema、本地 mock HTTP transport 和 scripted LangChain 模型；没有向开发业务库创建测试 Goal，没有访问真实外部 Proxy，也没有调用付费模型。

### 发布结果

已于 **2026-09-24 14:23（Asia/Shanghai）**发布到开发服务器 `47.97.82.200`。更新前应用备份位于 `/opt/agentdevstu/backups/goal-runtime-phase5-20260924/application.tar.gz`，已通过 tar 目录校验；备份目录权限 0700、文件 0600。部署文件 SHA256 清单位于同目录 `deployed-hashes.txt`。

服务器只合并 `features.goal_proxy_enabled=true`，保留已有 `goal_execution_enabled=true`、`goal_collaboration_enabled=true`、其余配置和 `.env`。没有执行数据库 DDL、迁移或测试数据写入。`agentdevstu.service` 重启后 ActiveState=active、SubState=running、ExecMainStatus=0，启动日志正常；运行环境确认新 Proxy Runtime 可导入、默认输入预算为 4000，OpenAPI 共 184 条路径。

首页、`/chat`、`/agents`、`/login` 返回 200；Goal options 与 Agent 详情匿名访问为 401。使用开发服务器实际静态资源、隔离 API 响应再次完成 Proxy 浏览器验收。回滚时优先关闭 `goal_proxy_enabled` 并恢复上述应用备份；Phase 3 数据结构和已有 Goal 文件保持不动，无数据库回滚操作。
