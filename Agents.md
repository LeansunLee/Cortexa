# AGENTS.md instructions for /Users/lisheng/Documents/ChatGPT/AgentDevStu

<INSTRUCTIONS>
# AgentDevStu

开发服务器账密信息
47.97.82.200
root
Leansun711 


PG数据库
* 服务器：47.97.82.200
* 端口：5432
* 数据库：agentdevstu
* 用户名：agentdevstu
* 密码：AgentDevStu2024

不要私自修改数据库的表结构，如果需要，请提前告诉我


## 开发基线版本

当前版本：**alpha v1.0.2609050000**
详见：[docs/ALPHA_v1.0.2609050000.md](docs/ALPHA_v1.0.2609050000.md)

包含：产品逻辑、系统架构、数据库表结构、API 端点、已完成功能清单、待开发事项、关键经验总结。

## 部署方式

- 修改并验证通过后，直接部署到开发服务器 `47.97.82.200`，无需再次询问；部署后检查服务状态和相关页面。
- 服务管理：systemd `agentdevstu.service`
- 环境变量：`/opt/agentdevstu/.env`
- 前端构建：`cd frontend && npm run build`
- 部署命令：`rsync` 到服务器 + `systemctl restart agentdevstu`

## 界面设计规范

所有页面遵循 [全站布局设计规范](docs/UI_LAYOUT_GUIDELINES.md)：无全局顶栏，账号固定侧栏底部，页面边距由应用框架统一提供。

## 关键经验

- SSE/Streaming 场景必须使用独立 DB session，不能复用 request-scoped session
- 大文本存文件系统，DB 只存摘要
- Vue ref 数组操作必须通过 `.value` 访问
- LLM 流式使用 LangChain `astream`
</INSTRUCTIONS>
