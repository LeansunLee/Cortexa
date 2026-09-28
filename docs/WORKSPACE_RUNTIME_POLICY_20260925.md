# Workspace Runtime Policy（运行策略）

工作空间管理员在「工作空间」页面配置 Execution Budget（执行预算）与 Collaboration Mode（协作模式）。策略写入现有 `t_workspaces.runtime_policy` JSONB；不新增表、列或迁移。未配置的工作空间继续使用平台默认预算和既有 Agent 协作模式。

## 有效策略

`runtime/policy.py` 统一按 Platform → Workspace → Agent → Goal 解析预算，并记录最终来源。未配置 Workspace 时采用现有默认值；Workspace 的有限数值可在平台字段上限内调高或调低，也可逐项勾选「不限」，取消该字段的应用运行预算上限。Agent 和 Goal 只能在 Workspace 分配的额度内收紧。Agent 运行预算沿用现有 `quality_policy.runtime.budget`，协作模式默认 `INHERIT_WORKSPACE`，工作空间配置变更后运行时重新读取。历史 Agent 显式保存的模式仍作为 Agent 级限制。用户明确 `@` 的参与者不受自主发现模式限制，但仍经过权限、可用性、输入契约、深度和预算检查。

策略 JSON 保持版本 `1`，例如：

```json
{
  "version": 1,
  "budget": {"llm_calls": 4, "max_collaborators": 2},
  "collaboration": {"max_autonomy": "ASK_BEFORE_COLLABORATION", "enabled": true, "candidate_limit": 2}
}
```

预算键沿用 `BudgetLimits` 的内部名称；UI 使用 `Max LLM Calls · 模型调用次数` 等英文名称和中文注释。有限数值按平台字段上限校验；勾选「不限」时该键保存为 JSON `null`，取消勾选后恢复可编辑的有限数值。运行时将 `null` 转为内部无上限标记，调试界面显示「不限」；模型供应商的上下文窗口、单次输出等外部约束依然生效。平台默认值不变，新增 `max_collaborators` 默认 `3`。管理 API 为 `GET/PUT /api/workspaces/{id}/runtime-policy`，均要求 `workspace.manage`；写入会合并策略命名空间，未知的历史 JSON 字段保持原样。

## 预算生命周期

- `NORMAL`：正常执行。
- `CONSERVE`：在非保留额度接近尾部时，仅暴露所需业务能力及尚未调用的显式协作 Agent，不安排非必要重新规划。
- `FINALIZING`：停止新能力调用，仅根据已有 Observation 输出结论并说明未完成部分。
- `EXHAUSTED`：记录耗尽资源、当前值、上限、运行角色、Agent 和阶段。

Runtime 从现有总预算内保留最多四分之一的输出额度（上限 4096）、一次 LLM 调用、一步和最多 30 秒用于收尾；不提高任何总预算。子 Agent 获得独立限额，按剩余参与者公平分配，且不得占用父 Runtime 的收尾保留。Proxy 协作也受独立时间额度限制。子 Agent 已有成功或部分 Observation 却因预算中断时返回 `PARTIAL`，供父 Agent 综合使用。

显式参与者数量、协作深度、模型调用和步骤的明显不足会在创建 Goal 前预检，不额外调用 LLM。Debug 轨迹展示来源、有效限额、已用和剩余值、预算阶段、子预算分配及失败明细；仍由现有调试权限控制。模型选择及调用入口保持原样。
