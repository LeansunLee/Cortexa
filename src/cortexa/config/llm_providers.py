from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _resolve_env(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2) or ""
        return os.getenv(var_name, default)

    return _ENV_PATTERN.sub(_replace, value)


@dataclass(frozen=True)
class ProviderConfig:
    kind: str  # "openai" | "anthropic" | "ollama"
    model: str
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    extra: dict[str, Any] = field(default_factory=dict)


def _resolve_value(value: Any) -> Any:
    if isinstance(value, str):
        return _resolve_env(value)
    if isinstance(value, dict):
        return {k: _resolve_value(v) for k, v in value.items()}
    return value


def _load_yaml_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parents[3] / "config.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return _resolve_value(raw)


def get_provider_config(name: str | None = None, config_path: Path | None = None) -> ProviderConfig:
    raw = _load_yaml_config(config_path)
    llm_block = raw.get("llm", {})
    providers = llm_block.get("providers", {})
    default_name = name or llm_block.get("default", "openai")

    if default_name not in providers:
        raise ValueError(
            f"Provider '{default_name}' not found in config.yaml. "
            f"Available: {list(providers.keys())}"
        )

    p = providers[default_name]
    return ProviderConfig(
        kind=p.get("kind", "openai"),
        model=p.get("model", "gpt-4o-mini"),
        api_key=p.get("api_key", ""),
        base_url=p.get("base_url", ""),
        temperature=float(p.get("temperature", 0.2)),
        max_tokens=int(p.get("max_tokens", 4096)),
        extra=p.get("extra", {}),
    )


# 场景目录：key -> (标题, 说明, 缺省策略)。缺省策略决定 config.yaml 未配置该场景时的行为：
#   "agent"     跟随智能体（旧路径 create_llm(agent.model)）
#   "workspace" 跟随调用方传入的工作空间默认（旧路径 create_llm(workspace.default_model_provider)）
#   "global"    全局默认供应商（旧路径 create_llm()）
# 即：model_routing 未配置时，所有场景行为与历史完全一致。
MODEL_SCENARIOS: dict[str, tuple[str, str, str]] = {
    "chat_reply": ("对话回复", "普通对话、追问后继续、上下文压缩等主回复链路", "agent"),
    "goal_execution": ("Goal 执行", "目标模式的多步执行与协作参与者", "agent"),
    "collaboration": ("协作任务", "Agent 互相委派的协作执行", "agent"),
    "workflow_node": ("工作流节点", "工作流中每个节点的一次模型调用", "agent"),
    "memory_extraction": ("记忆提取", "对话后的记忆提取、治理与协作认知沉淀", "agent"),
    "goal_analysis": ("目标智能拆解", "目标入口的一次问题拆解调用", "agent"),
    "work_candidates": ("工作候选提取", "对话后自动提取可分配的后续工作", "agent"),
    "title": ("对话命名", "首轮对话自动生成简洁标题", "agent"),
    "rag_summary": ("知识库文档摘要", "入库文档的摘要生成", "global"),
    "rag_retrieval": ("检索改写", "HyDE 假设片段与上下文化检索改写", "global"),
    "sql_draft": ("SQL 草稿", "数据能力 SQL 与参数草稿生成", "workspace"),
    "schema_generation": ("能力 Schema 生成", "数据能力输入 Schema 编辑", "workspace"),
}

SCENARIO_DEFAULT_LABELS = {"agent": "跟随智能体", "workspace": "跟随工作空间默认", "global": "全局默认"}


def resolve_model_name(
    agent: Any = None,
    scenario: str | None = None,
    fallback: str | None = None,
    config_path: Path | None = None,
) -> str | None:
    """模型解析链：场景覆盖 → 场景缺省策略 → 调用点回退 → 全局默认。

    config.yaml 每次现读，管理端保存 model_routing 后立即生效，无需重启。
    覆盖值指向已删除的供应商时回退到缺省策略，不让场景任务挂掉。
    """
    if scenario:
        routing = _load_yaml_config(config_path).get("model_routing") or {}
        choice = routing.get(scenario)
        if choice and choice != "agent" and provider_exists(choice, config_path):
            return choice
        if not choice:
            policy = MODEL_SCENARIOS.get(scenario, ("", "", "agent"))[2]
            if policy == "global":
                return None
    if agent is not None and getattr(agent, "model", None):
        return agent.model
    return fallback


def create_llm_for(
    agent: Any = None,
    scenario: str | None = None,
    fallback: str | None = None,
    config_path: Path | None = None,
) -> Any:
    """按场景解析供应商并构建模型实例；等价于 create_llm(resolve_model_name(...))。"""
    return create_llm(resolve_model_name(agent, scenario, fallback, config_path), config_path)


def provider_exists(name: str | None, config_path: Path | None = None) -> bool:
    """Whether a provider name exists in config.yaml; unknown names otherwise
    only fail at message time with a mid-stream error."""
    if not name:
        return False
    providers = _load_yaml_config(config_path).get("llm", {}).get("providers", {})
    return name in providers


def create_llm(name: str | None = None, config_path: Path | None = None) -> Any:
    cfg = get_provider_config(name, config_path)
    from cortexa.usage.collector import UsageCallback
    provider_name = name or _load_yaml_config(config_path).get("llm", {}).get("default", "openai")
    callbacks = [UsageCallback(provider_name, cfg.kind, cfg.model)]

    if cfg.kind == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "stream_usage": True,
            "callbacks": callbacks,
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        # Always pass api_key — empty string triggers a clear error
        # instead of silently falling back to OPENAI_API_KEY
        kwargs["api_key"] = cfg.api_key or "not-configured"
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        return ChatOpenAI(**kwargs)

    if cfg.kind == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "anthropic provider requires: pip install langchain-anthropic"
            ) from exc
        return ChatAnthropic(
            callbacks=callbacks,            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            api_key=cfg.api_key,
        )

    if cfg.kind == "ollama":
        try:
            from langchain_ollama import ChatOllama  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "ollama provider requires: pip install langchain-ollama"
            ) from exc
        return ChatOllama(
            callbacks=callbacks,            model=cfg.model,
            temperature=cfg.temperature,
            base_url=cfg.base_url or "http://localhost:11434",
        )

    raise ValueError(f"Unsupported provider kind: {cfg.kind}")
