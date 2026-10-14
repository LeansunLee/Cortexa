# 对话统一用户决策（2026-10-08）

## 用户交互

对话主流程展示「待你决策」卡片，标明提问 Agent、问题、选项和补充说明。支持单选、多选和自由填写；默认不选任何选项。用户点击「确认并继续」后才恢复原任务。等待回答时隐藏普通输入框，刷新页面仍能恢复问题。协作参与者授权也使用同一个卡片组件。

LLM 通过 `ask_user(question, options, multi_select, allow_free_text)` 提问。平台系统提示词要求涉及用户偏好、业务口径、执行方向和关键信息时使用此工具。主 LLM、协作 LLM、普通对话、目标执行、重新生成均提供这一入口。

Proxy 接收结构化 `ask_user` SSE 事件，或 JSON `status: awaiting_user` + `pending_ask`。`ok: false` 与 `awaiting_user` 表示等待用户，不表示执行失败。代理本地上下文整理缺少输入时，也生成问题卡片。

## 续接与保护

- Goal 等待原因 `user_decision_required`；保留模型消息、已完成查询、子 Agent 状态和预算。等待用户的时间不计入执行预算；续跑不重置已使用预算。
- 回答原子认领，校验问题 ID、会话所有者、空间和 Agent 使用权限；重复点击或旧标签页再次提交返回 409。
- 已完成工具结果保留，未执行的同批工具关闭消息记录；回答后先续接原子 Agent，再让主 Agent 汇总。
- Proxy 用服务器保存的 `session_id` 续接原外部会话。回答字段优先使用 `proxy_config.answer_field`，否则从原请求映射/唯一文本字段取得；不将原任务重新作为新会话派发。
- 外部接口必须支持会话续接协议。本次已同步为奔达公开 Agent API 增加可选 `session_id`，并保存私有消息检查点以支持服务重启恢复。补丁及隔离测试在 `integrations/benda-agent/`。
- HTTP 拒绝、超时、授权撤销和真正未知结果继续走原有保护。已派发的回答不会因网络失败自动重新调用；需核实执行结果。
- 模型的公开回复摘录和执行进度可展示；内部推理、代理凭证、会话 ID 和续接上下文不进入卡片或模型结果。

## API 与存储

- `GET /api/conversations/{id}/question`：当前公开问题。
- `POST /api/conversations/{id}/question/{question_id}/answer`：`selected_indices`（零起始）、`text`；返回现有对话 SSE。
- 复用 `Conversation.metadata_json` 存公开问题与私有文件引用；续接上下文保存于 `data/user_questions`，权限 0600。历史消息记录公开问题和用户回答。
- **没有数据库表结构变更。**

## 验证

隔离 PostgreSQL + 脚本模型/HTTP Transport 验证主 LLM、协作 LLM、协作 Proxy、普通 LLM、普通协作、独立 Proxy 的暂停与续接、重复提交、防止重复查询和会话标识不泄露。浏览器验证选择、失败保留、下一问题、刷新和输入框恢复。外部接口验证原 API 兼容与磁盘恢复。

## 真实对话的展示恢复补充

10 月 8 日反馈的真实销售计划已保存 5 个选项，Goal 为 `WAITING / user_decision_required`。该轮访问记录没有 `/question` 请求，客户端仍运行旧版 JS。统一补齐根入口 `/` 的 `no-store` 缓存控制；已打开的旧页面需刷新一次加载新代码。

决策卡片放在对应助手消息内，待决策消息不显示工作建议或重新生成按钮。消息 metadata 与 Goal 状态均可恢复公开问题，读取问题接口临时失败时仍可展示。使用这次真实的公开问题进行浏览器验证，保留原任务及外部会话，未重新派发。

## 回答提交后断线的修复

真实案例：回答已经送到代理，Cortexa 的连接中断将 Goal 记为取消，外部 Agent 在 28 秒后完成报告；旧卡片仍为 `answering`。已取回该原会话报告并让 Peter 完成汇总，未重新派发原任务或业务查询。

- 回答请求使用独立、受原 Goal 预算限制的后台任务，浏览器断开只解除流式订阅，任务继续保存结果。
- 刷新后的等待卡片定时读取最新状态；中断时展示已提交答案和「核实原会话并继续」，不再一直显示忙碌。
- `POST /conversations/{id}/question/{qid}/recover` 只读核实代理会话、原问题和已提交回答，三者均匹配且报告已完成时才恢复。
- 外部新增受 API Key 保护的 `GET /public/agent/sessions/{session_id}/result`；不调用模型或业务工具，不返回内部推理。
- 已完成报告进入 Observation、缓存和协作结果，主 Agent 保留原预算并完成汇总。重复恢复由 Goal revision CAS 拦截。
- Proxy 的公开工具进度、回复片段和已报告用量实时进入执行记录，内部推理事件不转发。
