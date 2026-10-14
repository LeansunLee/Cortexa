# Proxy 工具错误与任务错误分层（2026-10-09）

Peter 的预算反推任务在10:34:34收到 `mcp__excel_local__describe_workbook` 的工具错误事件。外部协议使用 `type: tool_result, status: error, ok: false` 表达一次工具失败；Agent 可继续改用其他工具。Cortexa 原来将所有事件的 `ok: false` 判成任务失败并主动关闭连接，导致状态变成结果未知。

只读原会话确认任务实际已完成，报告2991字，session ID、原始任务文本和代理契约匹配。

## 修复

- 完整 SSE 解析和增量 SSE 解析统一识别事件作用范围。`tool_start/tool_result/tool_error` 的失败不代表 Agent 任务终止。
- 仍要求任务终止事件，缺失终止事件、任务级error和失败终态不能冒充成功。
- 工具失败在执行记录中显示为错误，并注明 Agent 可继续处理。
- 任务级显式失败通过 `ProxyExecutionError` 记录为 FAILED observation、失败协作及审计记录；不会作为未知外部行动，也不会自动重复调用。
- 当前任务使用核实后的原报告恢复主流程；已回答决策卡仅在匹配当前 Goal 且恢复完成后清理等待状态。

## 验证

101项后端测试通过，包括工具错误后成功、真实任务失败、事件流中断、无完整终态、预算限制、Proxy Goal持久状态和用户决策续接。

没有修改外部数据服务、数据库结构或业务口径。
