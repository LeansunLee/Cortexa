# AgentDevStu

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
