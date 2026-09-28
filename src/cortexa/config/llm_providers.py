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
