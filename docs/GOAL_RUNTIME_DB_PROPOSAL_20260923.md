# Goal Runtime 数据库影响与变更方案（已批准、已迁移）

日期：2026-09-23。配套：[Phase 0 审计](GOAL_RUNTIME_PHASE0_20260923.md)。本文保留原始审批方案；下文待确认措辞属于历史记录。

执行记录（2026-09-23 Phase 3）：已按批准范围新增 Workspace.runtime_policy 和 t_runtime_goals，未 Backfill；迁移后结构复核通过，五张相关旧表行数保持不变。备份与验证详见 [Phase 3](GOAL_RUNTIME_PHASE3_20260923.md)。

审批记录（2026-09-23）：用户回复“好的，继续”，本方案已获批准。下文保留原始审批内容；Phase 1 不依赖新 schema，本阶段未执行迁移，获批结构留到 Phase 3 状态持久化阶段实施。

## 1. 结论与申请范围

推荐完整路线新增 **1 个 Workspace 列 + 1 张 Goal 状态表**，其余复用现有 JSON。批准后仍逐阶段实施：先交付不改主要行为的 Phase 1 Shadow；状态持久化在 Phase 3 使用，授权在 Phase 4 使用。数据库审批不等于允许一次实现全部阶段。

Phase 1/2 单独看不需要数据库修改。若只做短期、进程内 Goal，或接受把状态嵌在会话 metadata 并将 Workspace 策略留在 YAML，可以暂不新增表；但应明确它与本方案的运维、并发和恢复取舍。

## 2. 当前结构（已只读核对开发库）

| 对象 | 当前结构 | 可复用 / 缺口 |
| --- | --- | --- |
| `t_workspaces` | default_model_provider VARCHAR、system_prompt TEXT；没有通用配置 JSON | 缺结构化 Workspace budget/policy；自然语言 system_prompt 不能充当硬限制 |
| `t_agents` | collaboration / quality_policy / permissions / input_schema / output_schema 为 JSON；proxy_config 为 JSONB | 已足够承载 Agent 协作设置、预算配置与 Proxy 投影策略；不需要新增 autonomy 列 |
| `t_conversations` | owner_user_id、workspace_id、agent_id、metadata_json JSON | 能存轻量引用；没有独立 Goal 标识、状态、revision、幂等键 |
| `t_conversation_messages` | conversation_id、role、content、metadata_json JSON | 继续存回复、轻量 trace、goal_id；不把每条消息重定义为 Goal |
| `t_agent_collaborations` | conversation/source/target FK、status VARCHAR、call_depth；known_facts/constraints/result_sources 为 JSONB | 保留旧审计记录；result_sources 可加 runtime 引用；没有 Goal 授权生命周期 |
| `t_llm_usage_calls` | action、Provider/Model、Token、duration、status；usage_detail JSON | 扩展 usage_detail.runtime；不新增 Usage 列/索引 |

实库存在 `t_agents(workspace_id,id)` 唯一约束，可复用复合 FK。Conversation/Message 没有同样的跨列唯一约束。按名称检查未发现 Goal/Runtime/Budget 表。

部分 ORM 使用通用 JSON 而实库已有 JSONB（例如 proxy_config/result_sources）；本次不附带“统一类型”、历史状态重写或无关 schema 修复。

## 3. 目标结构

### 3.1 新增 `t_workspaces.runtime_policy`

- 类型：JSONB，可空，不设非空强制或历史填充值；NULL 表示继承平台默认。
- 新 CHECK：值为 NULL 或 JSON object。字段内部版本、枚举、合法范围由 Pydantic 校验。
- 内容域：version、budget、collaboration（允许的最高自主级别、候选上限等）、model_profiles（可选配置键映射）。不存 API Key、HTTP 凭证或 Prompt 正文。
- 平台配置先给硬上限，Workspace 只能收紧；Agent 和 Goal 同样不能突破上级。旧行读 NULL 时按代码默认解释，无需 UPDATE Backfill。
- 配置修改使用现有 workspace.manage；审批不是使用权，任何模型或 Agent 调用仍受实时权限控制。

### 3.2 新增 `t_runtime_goals`

用途仅为运行中或已结束 Goal 的小型检查点，不是 Workflow Engine，也不新建 Action/Observation/Trace 三套明细表。

| 字段 | 类型 / 空值 / 默认 | 用途 |
| --- | --- | --- |
| id | UUID，PK，应用生成 | 稳定 Goal ID |
| workspace_id | UUID，NOT NULL | Workspace 隔离 |
| owner_user_id | UUID，NOT NULL | 私有 Goal 的发起者 |
| conversation_id | UUID，NOT NULL | 关联现有会话 |
| initial_message_id | UUID，NOT NULL | 最初用户请求；回复/补参不替换起点 |
| agent_id | UUID，NOT NULL | 主 Agent |
| idempotency_key | VARCHAR(128)，NOT NULL | 一次新 Goal 请求的客户端/服务端稳定键；重新生成明确创建新键 |
| status | VARCHAR(16)，NOT NULL，默认 RUNNING | RUNNING / COMPLETE / BLOCKED / WAITING / FAILED |
| revision | INTEGER，NOT NULL，默认 1 | 乐观并发与授权提交版本 |
| state | JSONB，NOT NULL，默认空 object | version、目标摘要/来源、constraints、参与者集合、预算消耗、step/replan/failure、当前 Action、结果索引、等待原因 |
| artifacts | JSONB，NOT NULL，默认空 object | 完整 Goal/Observation/Invocation 内容的受控文件引用、hash、版本；不存任意用户路径 |
| created_at | TIMESTAMPTZ，NOT NULL，默认 now() | 创建时间 |
| updated_at | TIMESTAMPTZ，NOT NULL，默认 now() | 应用更新检查点时同步更新 |
| completed_at | TIMESTAMPTZ，可空 | COMPLETE/FAILED 的完成时间；BLOCKED/WAITING 不强行当成功 |

批准范围内的约束与索引：

- 主键 id。
- 唯一约束 `(workspace_id, owner_user_id, idempotency_key)`，拦截重复创建；补充 nonempty-key CHECK。
- FK workspace_id → t_workspaces.id（CASCADE）。
- FK owner_user_id → t_users.id（RESTRICT）；不改变现有用户删除策略。
- FK conversation_id → t_conversations.id（CASCADE）；initial_message_id → t_conversation_messages.id（CASCADE）。
- 复合 FK `(workspace_id, agent_id)` → t_agents(workspace_id,id)（RESTRICT），复用已有唯一约束；删除主 Agent 先结束/清理它的 Goal，不静默重派。
- CHECK status 属于上述五值、revision > 0、state/artifacts 为 JSON object；不新建 PostgreSQL ENUM。
- 一个查询索引 `(workspace_id, owner_user_id, conversation_id, updated_at, id)`，支持会话 Goal 列表。暂不添加 JSON GIN 或全 Trace 索引。

单列 Conversation/Message FK **不能**证明跨对象同 Workspace/同 owner/同 conversation。应用必须在同一事务中查验会话所有者、空间、主 Agent、初始消息归属，恢复时重新鉴权；加入与 Conversation 同等级的 ORM 私有过滤和写入校验。此次不为这一点偷偷增加旧表复合唯一约束。若后续需要数据库层全套复合约束，单独再提交方案。

`state` 只放有界摘要/ID/计数，建议应用控制序列化大小 ≤64KiB；原始目标文本可通过初始消息引用读取，长 Observation/Evidence 按现有文件存储模式持久化。文件访问继承 Goal 会话权限。轻量 Goal Trace 仍进入现有 debug_trace；本表不是第二套日志仓库。

## 4. 既有 JSON 的新增应用协议（不改列类型、不回填）

| 载体 | 新增内容 | 兼容解释 |
| --- | --- | --- |
| Agent.collaboration | autonomy、discovery 配置、目标可被发现设置 | 缺 autonomy 时在新路径解释为 EXPLICIT_ONLY；旧路径不受影响；需补 API/UI/版本快照 |
| Agent.quality_policy.runtime | version、budget、可选 profile 覆盖 | 缺省继承 Workspace / 平台；不得扩大硬限制 |
| Agent.proxy_config | versioned context_policy、input_budget、input/output 处理策略 | 既有 resolver 配置保留；严格新契约仅在新路径启用，缺省 default-deny |
| ConversationMessage.metadata_json | goal_id、runtime_version、轻量 Goal Trace | 历史消息无这些键正常显示；不批量修改历史消息 |
| AgentCollaboration.result_sources.runtime | goal_id/action_id、USER_EXPLICIT/USER_APPROVED/RUNTIME_AUTONOMOUS | 旧 items/memory_trace/memory_processed 保留 |
| UsageCall.usage_detail.runtime | purpose、requested_profile、complexity、risk、escalated、fallback、goal_id/action_id | 老报表仍读原字段；旧记录缺 purpose 展示 unknown，不伪造推断 |
| config.yaml | 平台 limits、feature flags、FAST/BALANCED/REASONING → Provider 配置键 | 复用 Provider/环境变量；不硬编码新模型，不引入新凭证存储 |

批准后仅对新配置/新运行写入这些协议。旧记录缺键按兼容默认读取，不执行数据搬迁或来源“补推断”。

## 5. Goal 授权、并发与恢复约定

- state 维护 explicit_agents、approved_agents、denied_agents、used_agents、candidate_agents；候选仅是发现结果。授权提交关联 Goal ID、当前 owner、revision、候选 ID，不能批准任意客户端伪造候选。
- approved/denied 仅在当前 Goal 内有效；用户拒绝后不再请求该 Agent。用户后续主动改变选择作为新的明确状态更新，不由模型撤销拒绝。
- 多次批准同一请求幂等；事务中行锁/版本 CAS 更新集合，预算预留与 Action ID 一并记录。等待用户时不保持长事务，调用 LLM/HTTP 时不占行锁。
- 执行前将 Action 标记 started；完成后提交 Observation 引用与预算结算。已完成 Action 不重复执行。
- 进程中断后 started 而没有结果的外部副作用，标为结果未知并进入 WAITING/BLOCKED；数据库检查点不能保证外部 HTTP exactly-once。只有目标支持幂等键或确认没有副作用时才允许自动重试。
- 取消持久化原因和部分结果，并保留现有 SSE partial-save 行为；不得把用户停止误报 COMPLETE。权限撤销后不可凭保存的 approved_agents 继续调用。
- 不在本阶段承诺通用后台自动恢复调度器；先支持有权限的显式恢复请求，保留既有 Post Runtime Cognition 生命周期。

## 6. 兼容方案

1. 所有结构增量添加；不重命名/删除旧列，不改既有 status 类型，不更新历史会话。
2. 旧程序忽略新列/新表，旧路径继续可用；新程序缺迁移时只运行旧/Shadow 路径，完整 Goal 路径启动检查给出明确不可用原因。
3. 三个独立开关至少区分 shadow、goal_execution、strict_proxy；默认关闭执行接管。现有 @ 顺序直到 Phase 4 开启新路径前保持原样。
4. Goal 读取权限按会话所有者；管理员不自动获得其他用户 Goal 正文。Memory 仍按 Agent 认知主体治理，不把 Goal 私有授权集合写成共享 Memory。
5. 保存 Agent 时只合并本次明确更新的配置，避免旧前端丢弃新 JSON 键；新版本 snapshot 保留策略，旧 snapshot 缺键仍能读取。

## 7. 迁移计划（获批后执行）

1. 独立测试库验证 upgrade、旧程序兼容、downgrade，并做真实 schema 前置检查；不通过应用启动自动 create_all 完成迁移。
2. 保存开发库 schema 与数据备份，记录迁移版本；不把凭证明文写入方案、日志或仓库。
3. 在短事务中添加 nullable Workspace 列及 CHECK、新 Goal 表与上述约束/索引；设置短 lock_timeout/statement_timeout，拿不到锁则回滚重试窗口，不长时间阻塞服务。
4. 检查已存在对象是否完全匹配预期；不能用 IF NOT EXISTS 静默接受不同类型/约束的同名对象。
5. 无历史 Backfill。验证列/表/索引/约束，旧数据数量与抽样可读性；新表初始为空。
6. 分阶段部署应用，先验证 Shadow、普通聊天、SSE/取消、Proxy、Knowledge/Memory/Data/Web、Usage、权限；完整 Goal 路径另按阶段验证后开启。

## 8. 风险与回滚

| 风险 | 控制 / 回滚 |
| --- | --- |
| ALTER TABLE 锁等待 | nullable 无历史批量更新；短锁超时；失败整事务回滚 |
| 多请求覆盖授权/预算 | revision + 行锁/CAS；持久化幂等键；外部执行不持锁 |
| 新 ORM 查询引用未迁移列 | 发布顺序与 readiness 检查；先完成 schema 再发布引用该字段的代码 |
| 新记录泄露跨用户/空间内容 | ORM 私有过滤 + 服务归属校验 + 恢复实时授权；负面测试覆盖 |
| DB 指针与文件不一致 | 临时文件原子落盘后提交引用；写失败不推进状态；孤儿文件延后清理，不误删用户数据 |
| 外部动作中断后重复执行 | 保留 action_id/执行阶段；未知结果不盲重试；可用时传目标幂等键 |
| 旧表 JSON 并发覆盖 | 命名空间合并并整体赋新值，必要时行锁；保留既有 metadata/Usage 字段 |
| 恢复后权限/策略变化 | 批准只免重复询问，不绕过实时硬限制；超限 BLOCKED/FAILED 并记录原因 |

优先回滚方式：关闭 goal_execution/strict_proxy，恢复旧应用路径，保留新增 schema 和记录，避免丢失已批准/拒绝及未知外部执行状态。Shadow 可单独关闭。旧应用不会消费新增键。

若确需物理撤销 schema：先停用新运行并导出新表/策略数据、备份相关文件，部署不引用新列的版本，再单独批准删除新增表和列。已产生的新 Goal 记录会随 DROP 丢失，因此不可将物理 downgrade 当作自动无损回滚。原有 JSON 新增命名空间可先留存，不批量清除历史；若要删除同样另行确认数据处理范围。

## 9. 等待确认

待确认的具体范围是：**允许按本文增量新增 Workspace.runtime_policy 和 t_runtime_goals（含列出的约束/索引），并在既有 JSON 中采用上述新协议，不做历史 Backfill。**

用户本次任务第 6 条要求涉及数据库修改时“先输出方案，然后 STOP”。现已到达该边界，后续代码、ORM、迁移和部署均等待确认。
