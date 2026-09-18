# AgentDevStu

## 当前开发资料

- [产品设计说明书（2026-09-18）](docs/PRODUCT_DESIGN_20260918.md)
- [知识库设计与编码规范（暂定版，2026-09-16）](docs/KNOWLEDGE_BASELINE_20260916.md)
- [项目需求、系统架构与下一期开发基线（2026-09-16）](docs/PROJECT_BASELINE_20260916.md)
- [现行 UI 布局、主题与控件规范](docs/UI_LAYOUT_GUIDELINES.md)
- [历史版本基线（alpha v1.0.2609050000）](docs/ALPHA_v1.0.2609050000.md)

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
uv run agentdevstu --goal "Research LangGraph and draft a short project outline"
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
uv run mypy src/agentdevstu
```
