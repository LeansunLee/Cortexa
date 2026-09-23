# AgentDevStu 开发基线版本

**版本**: alpha v1.0.2609230000\
**日期**: 2026-09-23\
**状态**: 开发中\
**前置版本**: alpha v1.0.2609050000\

---

## 一、本版本变更总览（2026-09-17 → 2026-09-23）

### 新增功能
1. **知识库描述体系**：独立知识库创建对话框支持填写描述；知识库菜单「重命名」升级为「编辑」，弹窗可同时修改名称与描述；新增 `PATCH /knowledge/{kb_id}/description` 接口
2. **智能体预设头像重设计**：17 个预设头像全部重绘为多元化人物（6 种肤色、东亚/南亚/东南亚/非洲/拉美/中东/欧美特征、性别多样、低调彩虹元素表达多元包容），每个角色独立背景色；新增 `AgentAvatar.vue` 内联渲染组件，预设头像跟随应用深浅主题（非预设上传头像仍走 `<img>`）
3. **Token 消耗页增强**：全页 Token 数值分级单位（≥1000 K、≥100 万 M、≥10 亿 B）；趋势柱顶展示输入/输出数值（40° 右上斜排、贴柱顶、单位带空格）；趋势下钻范围快照（点击柱子进当日明细，切回概览自动恢复原范围）；「今天/近 7 天/近 30 天」快捷范围点击即时查询
4. **玻璃主题浮层防穿透加固**：液态菜单底色半透明 + 模糊增强至 28px，磨砂 94% 半透明 + 38px 大模糊

### 修复
5. **全站卡片类 UI 主题语义变量整改**（11 个文件）：数据源、用户权限、登录页、工作、会议、聊天及知识库弹窗等历史页面的硬编码浅色写法全部改为语义变量（`--surface/--surface2/--text/--border/--success/--danger/--overlay`），深色主题下白底刺眼、状态徽章不可读的问题清除；新增回归测试 `frontend/tests/card-theme-audit.browser.cjs`
6. **知识库菜单玻璃主题文字穿透**：根因为浮层底色半透明且部分环境背景模糊未渲染；最终方案为液态 72%/88% 半透明 + 28px 模糊、磨砂 94%/96% + 38px 模糊（详见 UI 设计规范 2026-09-23 节）
7. **Token 趋势下钻后无法恢复范围**：下钻前快照查询范围，切回概览自动恢复；主动查询/重置放弃快照
8. **鼠标边缘泛光调优**：响应范围 180/125px → 130/95px，光强降低约 1/3，流动缓动 85ms → 150ms

### 技术尝试与回退
9. **Liquid Glass 折射增强（已回退）**：尝试用 SVG `feDisplacementMap` 位移贴图 + `backdrop-filter: url()` 实现 iOS Liquid Glass 式边缘折射，独立 PoC 验证视觉效果可行；但在真实页面 DOM 下 backdrop 滤镜会**静默失效**（CSS.supports 通过、渲染输出为空），导致浮层失去模糊与半透明质感。结论：该路线在当前 Chromium 上不可靠，相关代码已全部回退，待浏览器支持成熟后重新评估

### 数据库
- 无表结构变更（描述复用 `t_knowledge_bases.description` 既有字段）

---

## 二、产品定位

AgentDevStu 是一个 **AI 智能体管理平台**，用于创建、配置、管理和运行 AI 智能体。智能体代表公司部门、职能角色或某种职业，具有明确的人格、职责、能力边界和输入输出接口。平台支持多工作空间隔离，支持知识库、数据源、工作流编排和多智能体协作。

**核心价值主张**：让企业快速构建领域专家型 AI Agent，通过知识库和数据源赋予真实业务能力，通过对话和会议系统实现人机协作与多 Agent 协作。

---

## 三、系统架构

### 2.1 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 前端 | Vue 3 + Vite + Vue Router + CodeMirror | 单页应用，Lucide 图标库 |
| 后端 | Python 3.12 + FastAPI + Uvicorn | 异步框架，SSE 流式推送 |
| 数据库 | PostgreSQL 14+ (asyncpg + SQLAlchemy 2.0 async) | 20+ 张表 |
| LLM | LangChain (ChatOpenAI/Anthropic/Ollama) | 多供应商适配 |
| 知识检索 | BM25 关键词搜索 + jieba 分词 | 文件系统存储全文 |
| 部署 | 单机 47.97.82.200，systemd 管理 | 2 核 1.7GB 内存 |

### 2.2 后端模块

```
src/agentdevstu/
├── web/app.py              # FastAPI 应用入口 + SPA 静态文件服务
├── api/
│   ├── router.py           # API 路由注册
│   ├── deps.py             # 依赖注入（DB session, workspace）
│   ├── schemas.py          # Pydantic 请求/响应模型
│   ├── agents.py           # 智能体 CRUD + 测试 + 发布 + System Prompt 生成
│   ├── knowledge.py        # 知识库 CRUD + 文件上传 + 全文存储
│   ├── meetings.py         # 会议 CRUD + SSE 推送 + 多轮讨论
│   ├── conversations.py    # 对话 CRUD + SSE 流式 + 知识检索 + 数据源集成
│   ├── data_sources.py     # 数据源管理 + 凭证管理 + 连接测试
│   ├── workspaces.py       # 工作空间管理
│   ├── tools.py            # 工具管理
│   ├── workflows.py        # 工作流管理
│   └── tasks.py            # 任务管理
├── data/
│   ├── doc_storage.py      # 文档全文文件系统存储
│   └── adapter.py          # 数据源适配器（Postgres/MySQL/API）
├── db/
│   ├── models.py           # 20+ 张表的 SQLAlchemy ORM 模型
│   ├── engine.py           # async engine + session
│   └── encryption.py       # 凭证加密
├── rag/
│   └── retriever.py        # RAG 检索（向量检索 + BM25 fallback）
├── agents/
│   ├── agents.py           # Agent 执行引擎
│   └── proxy_executor.py   # Proxy 类型 Agent 执行器
├── workflow/
│   ├── engine.py           # 工作流执行引擎
│   ├── graph.py            # 工作流图结构
│   └── schema.py           # 工作流 Schema 定义
├── tools/
│   ├── exec_tool.py        # 工具执行
│   ├── rag.py              # RAG 检索增强
│   └── search.py           # 搜索工具
├── config/
│   ├── settings.py         # 全局配置
│   └── llm_providers.py    # LLM 供应商管理（支持 OpenAI/Anthropic/Ollama）
└── cli.py                  # CLI 入口
```

### 2.3 前端模块

```
frontend/src/
├── App.vue                 # 全局布局：侧边栏导航 + 工作空间选择器
├── router/index.js         # 7 个页面路由
├── api/index.js            # 所有 API 模块封装（axios）
└── views/
    ├── Dashboard.vue       # 首页仪表盘
    ├── Agents.vue          # 智能体管理（列表 + 9 Tab 编辑器 + 测试面板 + 知识库）
    ├── KnowledgeBases.vue  # 空间知识库管理（上传进度条）
    ├── Meetings.vue        # 会议管理（列表 + 创建 + 详情 SSE）
    ├── Chat.vue            # 对话系统（SSE 流式 + 搜索 + 重命名 + 重新生成）
    ├── DataSources.vue     # 数据源管理（连接测试 + 凭证管理）
    ├── Workflows.vue       # 工作流管理
    └── Settings.vue        # 系统设置（模型供应商 + 主题色配置）
```

### 2.4 数据库表（20+ 张）

| 表名 | 说明 |
|------|------|
| `t_workspaces` | 工作空间 |
| `t_agents` | 智能体配置（含 knowledge_base_ids, data_bindings） |
| `t_agent_versions` | 智能体版本快照 |
| `t_agent_runs` | 智能体运行记录 |
| `t_knowledge_bases` | 知识库（workspace_id + agent_id 两级） |
| `t_documents` | 知识库文档（content 列存摘要，全文存文件系统） |
| `t_document_chunks` | 文档分块（向量检索用） |
| `t_data_sources` | 数据源（Postgres/MySQL/API） |
| `t_data_credentials` | 数据源凭证（加密存储） |
| `t_data_capabilities` | 数据能力（查询模板 + Schema） |
| `t_data_schemas` | 数据 Schema |
| `t_data_access_policies` | 数据访问策略 |
| `t_data_queries` | 数据查询记录 |
| `t_agent_data_bindings` | Agent-数据能力绑定 |
| `t_rules` | 规则库 |
| `t_tools` | 工具 |
| `t_workflows` | 工作流 |
| `t_workflow_nodes` | 工作流节点 |
| `t_workflow_edges` | 工作流边 |
| `t_tasks` | 任务 |
| `t_task_runs` | 任务运行记录 |
| `t_conversations` | 对话 |
| `t_conversation_messages` | 对话消息 |
| `t_meetings` | 会议 |
| `t_meeting_rounds` | 会议轮次 |
| `t_meeting_messages` | 会议消息 |
| `t_meeting_participants` | 会议参与者 |
| `t_meeting_conclusions` | 会议结论 |
| `t_todo_items` | 待办事项 |
| `t_memories` | 记忆 |

### 2.5 API 端点汇总

| 模块 | 前缀 | 主要端点 |
|------|------|----------|
| 工作空间 | `/api/workspaces` | CRUD |
| 智能体 | `/api/agents` | CRUD + 测试 + 发布 + 版本 + 模型列表 |
| 知识库 | `/api/knowledge` | CRUD + 文件上传 + scope/agent_id 过滤 + 重索引 |
| 数据源 | `/api/data/sources` | CRUD + 连接测试 |
| 凭证 | `/api/data/credentials` | CRUD |
| 数据能力 | `/api/data/capabilities` | CRUD |
| 数据绑定 | `/api/data/bindings` | Agent-数据能力绑定 |
| 对话 | `/api/conversations` | CRUD + 消息 + **SSE 流式** + 重命名 + 重新生成 |
| 会议 | `/api/meetings` | CRUD + 启动 + 取消 + SSE 消息流 |
| 工作流 | `/api/workflows` | CRUD |
| 工具 | `/api/tools` | CRUD |
| 任务 | `/api/tasks` | CRUD |
| 配置 | `/api/config` | 供应商管理 + 默认模型 |
| 文档全文 | `/api/knowledge/{kb_id}/documents/{doc_id}/content` | 获取完整文档内容 |

---

## 四、核心产品逻辑

### 3.1 智能体（Agent）

**生命周期**：
```
创建 → 配置 → 保存草稿 → 测试 → 创建版本 → 发布 → 对话/被调用
```

**配置维度**（编辑器 9 个 Tab）：

| Tab | 字段 | 说明 |
|-----|------|------|
| 基础信息 | name, description, avatar, agent_type, tags | 头像支持上传裁剪 + 8 个预设 SVG（小米 SU7/YU7 车漆色系） |
| 人格 | personality | 15 个性格标签快速填入 |
| 职责 | role, responsibilities | 16 个预设角色（含研发/非研发岗：渠道、销售、品牌、营销） |
| 工作边界 | boundaries | 预设边界模板 |
| 工作方式 | behavior | 预设工作方式模板 |
| Proxy 配置 | proxy_config | endpoint, method, headers, 字段映射 |
| Schema | input_schema, output_schema | JSON Schema + CodeMirror 编辑 + 格式化按钮 + 示例提示 |
| 模型 | model, temperature, max_tokens, system_prompt | 工作空间默认模型 + 公共模型库 |
| 版本 | versions | 版本快照管理 |
| 知识库 | workspaceKBs + agentKBs | 空间共享 + Agent 独享 + 上传进度条 |
| 数据能力 | data_bindings | 绑定数据源查询能力 |

**智能体类型**：
- **LLM 智能体**：使用大模型推理，System Prompt 从配置字段自动拼接
- **Proxy 代理**：转发请求至外部系统 API，支持请求/响应字段映射

**System Prompt 自动生成策略**：
```
你是{name}。
## 人格特征\n{personality}
## 角色\n{role}
## 职责\n{responsibilities}
## 工作边界\n{boundaries}
## 工作方式\n{behavior}
## 补充说明\n{system_prompt}
## 参考知识\n{从知识库检索的相关内容}
## 可用数据查询能力\n{绑定的数据源能力描述}
```

### 3.2 知识库（Knowledge Base）

**两级知识库体系**：
- **空间知识库**（`agent_id = null`）：同工作空间所有 Agent 共享，Agent 通过勾选"使用"绑定
- **Agent 独立知识库**（`agent_id = 有值`）：仅该 Agent 独享，可在 Agent 编辑器中创建和管理

**存储优化**：
- DB `content` 列：仅存储摘要（≤2000 字符）
- 文件系统：`/opt/agentdevstu/data/documents/{doc_id}/content.txt` 存储全文
- 检索时按需从文件系统加载全文，避免 DB 膨胀

**检索策略**：
- 优先 BM25 关键词搜索（jieba 分词）
- 返回相关度最高的 3 篇文档，每篇截取前 1500 字符
- 超时保护（10s），失败不阻塞对话
- 文档有效期按上海时区日期判断：`valid_until = NULL` 表示永久有效，指定日期包含当天；过期文档保留原文件并允许管理员预览、下载和续期，但所有 Agent/RAG 检索路径都会排除

### 3.3 数据源系统（Data Source）

**数据源类型**：PostgreSQL / MySQL / API

**架构**：
```
数据源 (DataSource) → 凭证 (Credential) → 数据能力 (Capability) → Agent 绑定
```

- 数据源：连接配置（host, port, database）
- 凭证：加密存储的用户名密码
- 数据能力：查询模板 + 输入/输出 Schema
- Agent 绑定：Agent 关联数据能力，对话时自动注入工具描述

**连接测试**：支持 PostgreSQL / MySQL 连接验证 + API URL 测试

### 3.4 对话系统（Chat）

**核心特性**：
- **SSE 流式输出**：逐 token 推送，前端实时渲染 + 闪烁光标
- **知识库检索**：发送消息时自动检索相关知识，注入 System Prompt
- **数据源集成**：绑定数据能力的 Agent 可查询数据库
- **来源追踪**：每条回复显示信息来源（知识库/数据源）
- **对话搜索**：侧边栏搜索框，按标题/智能体名称过滤
- **对话重命名**：双击标题编辑
- **重新生成**：每条 assistant 消息可重新生成
- **键盘快捷键**：Enter 发送，Shift+Enter 换行

**流式架构**：
```
前端 fetch → SSE 连接 → 后端 async generator → LangChain astream → 逐 token yield
```

**会话管理**：
- 独立 DB session（`async_session_factory`），避免 SQLAlchemy 事务冲突
- 历史消息限制最近 20 轮，避免上下文过长

### 3.5 会议系统（AI Meeting）

**核心特性**：
- 创建会议：选择工作空间 Agent 参与、选择主持人、设定轮数（默认 3 轮）
- 会议目的：预设目标 + 自定义填写（必填）
- 会议附件：上传参考文件，内容注入 Agent 提示词
- SSE 实时推送：每轮讨论消息实时推送到前端
- 主持人总结：讨论结束后主持人 Agent 生成结论
- 冲突检测：多轮讨论中的观点冲突自动识别
- TodoList 生成：会议结束后输出待办事项

### 3.6 工作空间（Workspace）

资源隔离的组织单元：
- 每个工作空间独立管理 Agent、知识库、工具、工作流
- 工作空间默认模型配置
- 前端顶部工作空间切换器

---

## 五、性能优化经验

### 4.1 服务器资源管理

**问题**：2 核 1.7GB 内存服务器，uvicorn 进程独占 1.3GB，load average 飙到 21。

**解决方案**：
1. **Uvicorn 并发限制**：`--limit-concurrency 50 --timeout-keep-alive 30 --backlog 64`
2. **文档存储分离**：DB 只存摘要，全文存文件系统，DB 体积从 151MB 降至 185MB（含索引）
3. **systemd 管理**：EnvironmentFile 加载 `.env`，自动重启

**效果**：内存从 1.5GB 降至 253MB，Swap 从 2.5GB 降至 93MB。

### 4.2 SQLAlchemy 异步会话陷阱

**问题**：SSE StreamingResponse 中使用 FastAPI 依赖注入的 DB session，导致 `greenlet_spawn` 错误。

**根因**：StreamingResponse 的 async generator 在请求结束后才执行，此时 request-scoped session 已关闭。

**解决方案**：
- Streaming endpoint 不使用 `Depends(get_db)`
- 在 generator 内部创建独立 session：`async with async_session_factory() as db`
- 所有 DB 操作在 generator 内完成，generator 结束时 session 自动关闭

### 4.3 Vue 3 响应式陷阱

**问题**：`kb.doc_count = detail.documents.length` 设置后模板不更新。

**根因**：遍历 API 原始数组（`for (const kb of wsKBs)`）设置属性，不触发 Vue 响应式。

**解决方案**：遍历 `workspaceKBs.value` / `agentKBs.value`（Vue 代理对象）而非原始数组。

### 4.4 SSE 流式输出实现要点

1. **后端**：`async for chunk in model.astream(llm_messages)` 逐 token yield
2. **前端**：`fetch` + `ReadableStream` + `TextDecoder` 解析 SSE 事件
3. **渲染**：`streamContent` ref 实时追加 token，模板 `v-if="streaming && streamContent"` 显示
4. **光标**：CSS `::after` 伪元素 + `animation: blink` 闪烁效果
5. **超时保护**：知识库检索 `asyncio.wait_for(timeout=10)`，失败不阻塞对话

---

## 六、UI/UX 设计经验

### 6.1 主题色系统

- 12 种小米 SU7/YU7 车漆颜色作为预设
- CSS 变量：`--primary`, `--primary-hover`, `--primary-light`, `--primary-text`
- 设置页面支持用户自定义主题色（实时预览）
- 所有页面统一使用主题变量，确保换色一致性

### 6.2 图标规范

- 统一使用 Lucide 图标库，禁用 emoji
- 侧边栏导航、按钮、标签页、知识库等全部使用 Lucide 组件
- 头像系统：上传裁剪 + 17 个预设 SVG（多元人物扁平风，深浅主题自适应）
- 预设头像经 `AgentAvatar.vue` 内联渲染：底色/描边由 `html[data-theme]` 驱动，SVG 文件内嵌 `prefers-color-scheme` 作为独立引用时的兜底；组件对非预设路径自动回退 `<img>`

### 6.3 页面布局

- 左侧导航栏（固定 200px）+ 右侧内容区
- 对话页面：左侧对话列表（280px）+ 右侧聊天区
- 设置页面：自适应高度，避免超出视口
- 所有页面标题移至侧边栏，工作空间选择器移至左侧

---

## 七、已完成功能清单

### 基础设施
1. ✅ 工作空间管理（多空间切换 + 主题色配置）
2. ✅ 数据库表结构设计（20+ 张表）
3. ✅ systemd 服务管理 + 环境变量配置
4. ✅ Uvicorn 并发限制 + 内存优化

### 智能体系统
5. ✅ 智能体 CRUD + 版本管理 + 发布
6. ✅ 智能体类型：LLM + Proxy
7. ✅ 智能体配置：人格/职责/边界/工作方式/Schema/模型（9 Tab 编辑器）
8. ✅ 预设功能：15 个人格标签、16 个角色预设（含非研发岗）、边界/方式预设
9. ✅ 头像上传 + 裁剪（含缩放） + 8 个预设 SVG 头像
10. ✅ System Prompt 自动从配置生成 + 知识库/数据源注入
11. ✅ 智能体测试面板（CodeMirror JSON 编辑 + 快速模板 + 格式化）

### 知识库系统
12. ✅ 知识库两级体系（空间共享 + Agent 独享）
13. ✅ 知识库文件上传（文本 + 二进制 + PDF 文本提取）
14. ✅ 文档全文文件系统存储（DB 只存摘要）
15. ✅ BM25 关键词检索 + jieba 中文分词
16. ✅ 上传进度条 + 文档数量统计
17. ✅ 文档 LLM 摘要：上传/PDF 识别后由 LLM 生成检索导向摘要存入 documents.content（rag/summary.py，后台任务不阻塞上传，失败自动回退截断摘要）
18. ✅ 两段式知识检索：先按 content 摘要定位文档（agents/knowledge.py），再对选中文档做全文窗口提取；摘要无命中时自动回退全文扫描
19. ✅ 存量摘要回填脚本（scripts/backfill_doc_summaries.py）

### 数据源系统
17. ✅ 数据源管理（PostgreSQL / MySQL / API）
18. ✅ 凭证加密存储
19. ✅ 数据能力（查询模板 + Schema）
20. ✅ 连接测试功能
21. ✅ Agent 数据能力绑定

### 对话系统
22. ✅ 对话 CRUD + 历史对话管理
23. ✅ **SSE 流式输出**（逐 token 渲染 + 闪烁光标）
24. ✅ 知识库检索集成（BM25 + 超时保护）
25. ✅ 数据源能力注入
26. ✅ 信息来源追踪
27. ✅ 对话搜索 + 重命名 + 重新生成
28. ✅ 键盘快捷键（Enter 发送，Shift+Enter 换行）
29. ✅ 错误处理 + 重试按钮

### 会议系统
30. ✅ 会议 CRUD + 创建/启动/取消
31. ✅ 多 Agent 多轮讨论 + SSE 实时推送
32. ✅ 主持人总结 + 冲突检测
33. ✅ 会议附件上传
34. ✅ TodoList 生成

### 前端体验
35. ✅ 侧边栏导航 + SPA 路由
36. ✅ 模型供应商配置 + 工作空间默认模型
37. ✅ 主题色配置（12 种车漆颜色）
38. ✅ Lucide 图标统一替换
39. ✅ 页面布局优化（间距、高度自适应）
40. ✅ 静态资源 Cache-Control 防缓存
41. ✅ 知识库描述：创建/编辑全链路（独立库 + 空间库），卡片展示
42. ✅ 预设头像多元化重设计 + 主题跟随内联渲染
43. ✅ Token 消耗页分级单位与趋势柱顶数值
44. ✅ 模型用量趋势下钻范围快照
45. ✅ 全站卡片类 UI 深色主题语义变量整改 + card-theme-audit 回归

---

## 八、部署信息

| 项目 | 值 |
|------|-----|
| 服务器 | 47.97.82.200 (root / Leansun711) |
| 项目路径 | `/opt/agentdevstu/` |
| 数据库 | PostgreSQL `agentdevstu` (5432, user: agentdevstu) |
| 服务管理 | systemd `agentdevstu.service` |
| 启动命令 | `uvicorn ... --limit-concurrency 50 --timeout-keep-alive 30` |
| 环境变量 | `/opt/agentdevstu/.env`（MIMO_API_KEY 等） |
| 前端构建 | `cd frontend && npm run build` → `src/agentdevstu/web/static/dist/` |
| 部署方式 | `rsync` 到服务器 + `systemctl restart agentdevstu` |
| 文档存储 | `/opt/agentdevstu/data/documents/{doc_id}/content.txt` |

---

## 九、待开发事项

### 高优先级
- [ ] 对话消息分页加载（当前一次加载全部）
- [ ] Markdown 渲染优化（代码高亮、表格渲染）
- [ ] 对话导出（Markdown/PDF）
- [ ] 消息编辑功能

### 中优先级
- [ ] 工作流引擎完善（框架已建）
- [ ] 工具系统接入实际工具
- [ ] 记忆系统实现（短期/长期记忆）
- [ ] 规则库实现
- [ ] Agent 运行记录可视化

### 低优先级
- [ ] Office 文档在线编辑（已调研：OnlyOffice 自托管为唯一保真方案，涉新增常驻服务，暂缓）
- [ ] Liquid Glass 折射增强（feDisplacementMap 方案已验证可行，待 Chromium backdrop url() 渲染成熟后重启）
- [ ] 向量检索（BGE-M3 + Ollama）替代 BM25
- [ ] 多模态支持（图片/文件理解）
- [ ] Agent 市场（模板共享）
- [ ] 批量导入/导出

---

## 十、关键经验总结

### 架构层面
1. **存储分离**：大文本（文档全文）存文件系统，DB 只存元数据和摘要，是小内存服务器的关键优化
2. **摘要即检索索引**：documents.content 存 LLM 生成的检索导向摘要（保留型号/参数/政策等关键检索词），检索先摘要定位、后全文取窗口；LLM 摘要约 10-20 秒，必须放后台任务，不能阻塞上传接口
3. **异步会话隔离**：SSE/Streaming 场景必须使用独立 DB session，不能复用 request-scoped session
4. **systemd 管理**：比手动 `nohup` 更可靠，支持自动重启和日志管理

### 产品层面
5. **预设 > 手动**：角色、人格、边界等配置项提供预设选项，降低用户配置成本
6. **流式 > 等待**：SSE 流式输出是对话体验的质变点，用户感知响应时间大幅降低
7. **来源追踪**：知识库/数据源来源展示增加用户信任感

### 开发层面
8. **Vue 响应式**：操作 ref 数组时必须通过 `.value` 访问，直接操作原始数组不触发更新
9. **LLM 流式**：LangChain `astream` 是最可靠的流式方案，兼容 OpenAI/Anthropic/Ollama
10. **增量部署**：`rsync --checksum` 只传输变化文件，部署速度快
11. **backdrop url() 不可靠**：`backdrop-filter: url(#svg-filter)` 在 Chromium 真实页面会静默失败（CSS.supports 通过但渲染输出为空），导致浮层丢失模糊与半透明；玻璃质感必须依赖原生 `blur()` 滤镜函数，浮层穿透用「增强模糊 + 适度底色透明度」解决，不能用提高不透明度的方式（会杀死玻璃感）
12. **scoped 样式回归测试**：Vue scoped 样式编译产物带 `data-v-xxx` 属性选择器且每次构建 hash 变化，静态复现页面需从构建产物动态提取 hash 注入元素，或剥除属性选择器
13. **浮层修订号并发控制**：文档编辑/摘要/索引等后台任务用 `content_revision`/`summary_revision` 修订号做乐观校验，任务完成时 revision 不一致则丢弃结果，防止旧任务覆盖新编辑

---

*此文档作为 alpha v1.0.2609230000 版本的开发基线，记录了从 v1.0.2609050000 以来的所有架构演进、产品迭代和经验教训。全量架构与产品逻辑沿用上一版章节（二至四），本版本重点见「一、本版本变更总览」。*
