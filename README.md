# Cortexa

Python 导入包为 `cortexa`（`src/cortexa`），命令行入口为 `cortexa` 和 `cortexa-web`。开发服务器沿用 `/opt/agentdevstu` 部署目录和 `agentdevstu.service` 服务标识；服务启动模块已改为 `cortexa.web.app:app`，配置见 `deploy/agentdevstu.service`。数据库名称、会话 Cookie 和加密密钥标识保持原值，以保留现有数据与登录状态。

## 当前开发资料

- [最新产品设计与 Memory 2.0 实施基线（含 2026-09-20 UI 更新）](docs/PRODUCT_DESIGN_20260919.md)
- [Memory 2.0 现状审计（2026-09-19）](docs/MEMORY_2_AUDIT_20260919.md)
- [Memory 2.0 数据库与领域模型方案（已批准，设计留档）](docs/MEMORY_2_DESIGN_PROPOSAL_20260919.md)
- [产品设计说明书（2026-09-18）](docs/PRODUCT_DESIGN_20260918.md)
- [知识库设计与编码规范（暂定版，2026-09-16）](docs/KNOWLEDGE_BASELINE_20260916.md)
- [项目需求、系统架构与下一期开发基线（2026-09-16）](docs/PROJECT_BASELINE_20260916.md)
- [现行 UI 布局、主题与控件规范](docs/UI_LAYOUT_GUIDELINES.md)
- [历史版本基线（alpha v1.0.2609050000）](docs/ALPHA_v1.0.2609050000.md)

记忆管理当前入口为「Agent 运维 → 记忆」。最新产品基线第 10 节包含弹窗操作、筛选行为、召回规则参数及帮助说明；所有界面统一使用“记忆”。UI 更新实现提交为 36333b4，已部署到现有开发服务器。

以下为项目早期 CLI 示例说明；完整 Web 平台范围与当前实现边界参见上述开发基线。

A LangGraph multi-agent project with configurable multi-provider LLM support.

## Supported providers

| Provider    | kind      | Example model         | Config key       |
|-------------|-----------|-----------------------|------------------|
| OpenAI      | openai    | gpt-4o-mini           | `openai`         |
| DeepSeek    | openai    | deepseek-chat         | `deepseek`       |
| Moonshot    | openai    | moonshot-v1-8k        | `moonshot`       |
| Zhipu/GLM   | openai    | glm-4-flash           | `zhipu`          |
| Anthropic   | anthropic | claude-sonnet-4-20250514 | `anthropic`   |
| Ollama      | ollama    | qwen2.5:7b            | `ollama`         |

Any OpenAI-compatible API (Azure, Together, Groq, etc.) can be added by setting `kind: openai` with a custom `base_url`.

## Quick start

```bash
# 1. Configure provider in config.yaml (set "default" to your provider)
# 2. Fill API key in .env
cp .env.example .env

# 3. Run
uv run cortexa --goal "Research LangGraph and draft a short project outline"
```

## Config structure (config.yaml)

```yaml
llm:
  default: deepseek        # switch provider here
  providers:
    deepseek:
      kind: openai          # "openai" | "anthropic" | "ollama"
      base_url: "https://api.deepseek.com/v1"
      model: deepseek-chat
      api_key: "${DEEPSEEK_API_KEY}"
      temperature: 0.2
```

## Validate

```bash
uv run ruff check src scripts docs examples
uv run mypy src/cortexa
```
