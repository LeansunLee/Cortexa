# Cortexa 开发基线版本

**版本**: alpha v1.0.2609030852  
**日期**: 2026-09-03  
**状态**: 开发中  

---

## 一、产品定位

Cortexa 是一个 **AI 智能体管理平台**，用于创建、配置、管理和运行 AI 智能体。智能体代表公司部门、职能角色或某种职业，具有明确的人格、职责、能力边界和输入输出接口。平台支持多工作空间隔离，支持工作流编排和多智能体协作。

---

## 二、核心产品逻辑

### 2.1 智能体（Agent）

智能体是平台的核心实体，生命周期为：

```
创建 → 配置 → 保存草稿 → 测试 → 创建版本 → 发布 → 对话/被调用
```

**配置维度**（编辑器 9 个 Tab）：

| Tab | 字段 | 说明 |
|-----|------|------|
| 基础信息 | name, description, avatar, agent_type, tags | 头像支持上传裁剪 + 8 个预设 SVG |
| 人格 | personality | 15 个性格标签快速填入 |
| 职责 | role, responsibilities | 16 个预设角色（含研发/非研发岗） |
| 工作边界 | boundaries | 预设边界模板 |
| 工作方式 | behavior | 预设工作方式模板 |
| Proxy 配置 | proxy_config | endpoint, method, headers, 字段映射 |
| Schema | input_schema, output_schema | JSON Schema + CodeMirror 编辑 + 格式化按钮 |
| 模型 | model, temperature, max_tokens, system_prompt | 工作空间默认模型 + 公共模型库 |
| 版本 | versions | 版本快照管理 |
| 知识库 | workspaceKBs + agentKBs | 空间共享 + Agent 独享 |

**智能体类型**：
- **LLM 智能体**：使用大模型推理，System Prompt 从配置字段自动拼接
- **Proxy 代理**：转发请求至外部系统 API，支持请求/响应字段映射

**System Prompt 自动生成策略**（`_build_system_prompt`）：
```
你是{name}。
## 人格特征\n{personality}
## 角色\n{role}
## 职责\n{responsibilities}
## 工作边界\n{boundaries}
## 工作方式\n{behavior}
## 补充说明\n{system_prompt}（仅手动填写时）
## 输出格式要求\n（仅填写 output_schema 时）
```

### 2.2 知识库（Knowledge Base）

两级知识库体系：

- **空间知识库**（`agent_id = null`）：同工作空间所有 Agent 共享，Agent 通过勾选"使用"绑定
- **Agent 独立知识库**（`agent_id = 有值`）：仅该 Agent 独享，可在 Agent 编辑器中创建和管理

支持文件上传（文本 UTF-8 / 二进制 base64），文档列表展示，删除管理。

### 2.3 会议系统（AI Meeting）

多智能体协作讨论模块，支持：

- 创建会议：选择工作空间 Agent 参与、选择主持人、设定轮数（默认 3 轮）
- 会议目的：预设目标 + 自定义填写（必填）
- 会议附件：上传参考文件，内容注入 Agent 提示词
- SSE 实时推送：每轮讨论消息实时推送到前端
- 主持人总结：讨论结束后主持人 Agent 生成结论
- 冲突检测：多轮讨论中的观点冲突自动识别
- TodoList 生成：会议结束后输出待办事项

### 2.4 对话系统（Chat）

用户与智能体的实时对话：

- 选择当前工作空间的已发布 Agent 创建对话
- 历史对话列表管理
- 消息发送与接收
- System Prompt 自动从 Agent 配置生成

### 2.5 工作空间（Workspace）

资源隔离的组织单元：

- 每个工作空间独立管理 Agent、知识库、工具、工作流
- 工作空间默认模型配置
- 前端顶部工作空间切换器

---

## 三、系统架构

### 3.1 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Vue 3 + Vite + Vue Router + CodeMirror |
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| 数据库 | PostgreSQL 14+ (asyncpg + SQLAlchemy 2.0 async) |
| 部署 | 单机部署 47.97.82.200 |

### 3.2 后端模块

```
src/agentdevstu/
├── web/app.py              # FastAPI 应用入口 + SPA 静态文件服务
├── api/
│   ├── router.py           # API 路由注册
│   ├── deps.py             # 依赖注入（DB session, workspace）
│   ├── schemas.py          # Pydantic 请求/响应模型
│   ├── agents.py           # 智能体 CRUD + 测试 + 发布 + System Prompt 生成
│   ├── knowledge.py        # 知识库 CRUD + 文件上传（空间/Agent 两级）
│   ├── meetings.py         # 会议 CRUD + SSE 推送 + 多轮讨论 + 总结
│   ├── conversations.py    # 对话 CRUD + LLM 调用
│   ├── workspaces.py       # 工作空间管理
│   ├── tools.py            # 工具管理
│   ├── workflows.py        # 工作流管理
│   └── tasks.py            # 任务管理
├── db/
│   ├── models.py           # 16 张表的 SQLAlchemy ORM 模型
│   ├── engine.py           # async engine + session
│   └── meetings.py         # 会议相关数据库操作
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
│   └── llm_providers.py    # LLM 供应商管理
└── cli.py                  # CLI 入口
```

### 3.3 前端模块

```
frontend/src/
├── App.vue                 # 全局布局：侧边栏导航 + 工作空间选择器
├── router/index.js         # 7 个页面路由
├── api/index.js            # 所有 API 模块封装（axios）
└── views/
    ├── Dashboard.vue       # 首页仪表盘
    ├── Agents.vue          # 智能体管理（列表 + 编辑器 + 测试面板）
    ├── KnowledgeBases.vue  # 空间知识库管理
    ├── Meetings.vue        # 会议管理（列表 + 创建 + 详情 SSE）
    ├── Chat.vue            # 对话系统
    ├── Workflows.vue       # 工作流管理
    └── Settings.vue        # 系统设置（模型供应商配置）
```

### 3.4 数据库表（16 张）

| 表名 | 说明 |
|------|------|
| `t_workspaces` | 工作空间 |
| `t_agents` | 智能体配置 |
| `t_agent_versions` | 智能体版本快照 |
| `t_agent_runs` | 智能体运行记录 |
| `t_knowledge_bases` | 知识库（workspace_id + agent_id 两级） |
| `t_documents` | 知识库文档 |
| `t_rules` | 规则库 |
| `t_tools` | 工具 |
| `t_workflows` | 工作流 |
| `t_workflow_nodes` | 工作流节点 |
| `t_workflow_edges` | 工作流边 |
| `t_tasks` | 任务 |
| `t_task_runs` | 任务运行记录 |
| `t_conversations` | 对话 |
| `t_conversation_messages` | 对话消息 |
| `t_memories` | 记忆（短期/长期） |

### 3.5 API 端点汇总

| 模块 | 前缀 | 主要端点 |
|------|------|----------|
| 工作空间 | `/api/workspaces` | CRUD |
| 智能体 | `/api/agents` | CRUD + 测试 + 发布 + 版本 + 模型列表 |
| 知识库 | `/api/knowledge` | CRUD + 文件上传 + scope/agent_id 过滤 |
| 对话 | `/api/conversations` | CRUD + 消息发送 |
| 会议 | `/api/meetings` | CRUD + 启动 + 取消 + SSE 消息流 |
| 工作流 | `/api/workflows` | CRUD |
| 工具 | `/api/tools` | CRUD |
| 任务 | `/api/tasks` | CRUD |
| 配置 | `/api/config` | 供应商管理 + 默认模型 |

---

## 四、部署信息

| 项目 | 值 |
|------|-----|
| 服务器 | 47.97.82.200 (root /leansun711) |
| 项目路径 | `/opt/agentdevstu/` |
| 数据库 | PostgreSQL `agentdevstu` (5432) |
| 启动命令 | `cd /opt/agentdevstu && PYTHONPATH=/opt/agentdevstu/src /usr/local/python3.12/bin/python3.12 -m uvicorn agentdevstu.web.app:app --host 0.0.0.0 --port 8000` |
| 前端构建 | `cd frontend && npm run build` → `src/agentdevstu/web/static/dist/` |
| 部署方式 | rsync + scp 到服务器，fuser -k 8000/tcp 后重启 uvicorn |

---

## 五、已完成功能清单

1. ✅ 工作空间管理（多空间切换）
2. ✅ 智能体 CRUD + 版本管理 + 发布
3. ✅ 智能体类型：LLM + Proxy
4. ✅ 智能体配置：人格/职责/边界/工作方式/Schema/模型
5. ✅ 预设功能：15 个人格标签、16 个角色预设、边界/方式预设
6. ✅ 头像上传 + 裁剪（含缩放） + 8 个预设 SVG 头像
7. ✅ System Prompt 自动从配置生成
8. ✅ 智能体测试面板（CodeMirror JSON 编辑 + 快速模板）
9. ✅ 知识库两级体系（空间共享 + Agent 独享）
10. ✅ 知识库文件上传（文本 + 二进制）
11. ✅ 对话系统（选择 Agent + 历史对话 + 消息收发）
12. ✅ 会议系统（创建/启动/多轮 SSE 讨论/主持人总结/TodoList）
13. ✅ 会议附件上传（参考文件注入提示词）
14. ✅ 前端侧边栏导航 + SPA 路由
15. ✅ 模型供应商配置 + 工作空间默认模型
16. ✅ 静态资源 Cache-Control 防缓存
17. ✅ JSON Schema CodeMirror 编辑 + 格式化 + 示例提示

---

## 六、待开发 / 已知问题

- 工作流引擎（框架已建，待完善）
- 工具系统（框架已建，待接入实际工具）
- 记忆系统（表结构已建，待实现）
- 规则库（表结构已建，待实现）
- RAG 知识检索（框架已建，待实现向量检索）
- 对话中知识库检索集成
- Agent 运行记录可视化
- 更多预设头像 SVG

---

*此文档作为 alpha v1.0.2609030852 版本的开发基线，后续开发以此为参考。*
