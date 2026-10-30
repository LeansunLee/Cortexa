# 隐藏配置参数审计（2026-10-30）

背景：`features.goal_proxy_enabled` 曾在生产上丢失，导致 Proxy 代理静默退出协作候选（用户无法感知）。该参数已于 2026-10-30 移除——Proxy 代理能否参与目标协作只取决于自身的 `goal_contract.enabled`。本文顺带盘点系统中其余"只存在于文件、UI/界面上看不见"的参数，避免同类问题再次发生。

配置读取共三种机制：

- `config.yaml`：`execution_config()`（goals.py，每次请求读盘）、`feature_flag()`（config/settings.py）、`shadow_enabled()`（runtime/shadow.py）——全部无写入 API，改完需重启服务（个别只读不缓存的除外）。
- `.env`（服务器 `/opt/agentdevstu/.env`）：`load_env()` 启动时注入，改完需重启。
- 代码内默认值：配置缺失时静默回退，参数"不存在"与"取默认值"不可区分。

## config.yaml · features

**2026-10-30 更新：以下 7 个开关已收敛到管理员设置页**（系统配置页「平台功能开关」卡片，`GET/PUT /api/config/features`，`config.manage` 权限门控，保存即生效无需重启，见 commit 2411c22）。下表保留作为实现说明；`.env` 与 `runtime:` 块仍为纯文件配置。

| 参数 | 读取位置 | 作用 | 缺失时 |

| 参数 | 读取位置 | 作用 | 缺失时 |
| --- | --- | --- | --- |
| `goal_execution_enabled` | api/goals.py:151 | 目标模式总入口，false 时消息一律走普通对话 | false |
| `goal_collaboration_enabled` | api/goals.py 多处、api/collaboration.py、runtime/collaboration.py | Agent 协作总入口（候选目录、授权、模式选项） | false |
| `goal_shadow_enabled` | runtime/shadow.py `shadow_enabled()` → api/conversations.py | 普通对话中影子跟踪目标意图（不执行） | false |
| `capability_shadow_enabled` | runtime/capture.py | 普通对话中能力影子采集（为路由积累数据） | false |
| `conversation_debug_enabled` | api/conversations.py:64 | 调试轨迹平台开关。半 UI：个性化页有「调试」开关，但需 `conversation.debug` 权限且平台开关同时为 true | false |
| `external_tools_enabled` | tools/registry.py:315 | 外部 HTTP/MCP 工具整体灰度 | true |
| `skills_enabled` | tools/skills.py:182 | 技能索引整体灰度 | true |

注意 `external_tools_enabled` 与 `skills_enabled` 的默认值是 **true**（缺省即开），与 goal 系列（缺省即关）相反——配置文件里没写这两行不代表功能关闭。

## config.yaml · runtime（代码支持但两份 config.yaml 都没写——纯隐藏块）

| 参数 | 读取位置 | 作用 |
| --- | --- | --- |
| `runtime.budget.*` | runtime/policy.py:34 `platform_hard_limits()` | 平台级预算硬顶，覆盖 workspace/goal 各层预算 |
| `runtime.collaboration.max_autonomy / enabled / candidate_limit` | runtime/policy.py:63 | 平台级协作策略层，参与 min() 合并 |

这两块只在代码里存在，config.yaml 中没有模板行；不写即用代码默认（协作 AUTONOMOUS、预算默认上限）。如果要收紧平台级预算，只能"发明"这个块。

## config.yaml · llm（部分暴露）

`llm.default` 与 `llm.providers.*` 经 `GET /api/agents/models/available` 暴露给前端模型下拉框，但**只能读不能改**——增删改供应商、改 base_url/模型名仍需改文件。provider 的 `api_key` 用 `${ENV_VAR}` 占位，真实值在 `.env`。

## .env（服务器 /opt/agentdevstu/.env，全部无 UI）

| 变量 | 读取位置 | 作用 |
| --- | --- | --- |
| `DATABASE_URL` | db/engine.py:9 | 不设则回退到硬编码的开发库连接串 |
| `${各供应商}_API_KEY` | config.yaml `${}` 占位展开 | 模型供应商密钥 |
| `WEB_SEARCH_PROVIDER` / `SEARXNG_URL` | tools/web_search.py 等 | 内置搜索后端选择与地址 |
| `QUESTION_AUTO_ANSWER_TIMEOUT` | conversation/questions.py:44 | 提问自动继续的超时秒数，默认 3600 |
| `DATA_ENCRYPT_KEY` | 相应加解密模块 | 数据加密密钥 |
| `KNOWLEDGE_MAX_DOCS` / `KNOWLEDGE_SEARCH_MAX_TOP_K` | 知识库检索 | 检索规模上限 |
| `LIBREOFFICE_BIN` / `TESSERACT_BIN` | 文档转换 / OCR | 外部二进制路径 |
| `SKILLS_STORAGE_DIR` / `USAGE_SPOOL_PATH` / `WORK_STORAGE_DIR` | 各存储模块 | 目录覆盖 |
| `LLM_PROVIDER` | config/settings.py:22 | 单独的 provider 选择入口（与 config.yaml `llm.default` 并存，注意两处口径） |

## 建议

1. **删参数就是修 bug**：`goal_proxy_enabled` 属于"平台开关挡住了本来合法的行为，开关一丢功能静默消失"。其余 goal 系列开关是功能分期的产物，保留合理，但它们的缺失语义（false）与灰度类（true）不一致，读配置时要留意。
2. 平台预算硬顶与平台协作层（`runtime:` 块）建议在 config.yaml 中补上模板行并注释默认值，避免"想收紧却不知道块名"。
3. 长期方向：把需要运维感知的开关收敛到管理员设置页（写回 config.yaml + 自动重启），文件只保留密钥与机器相关路径。
