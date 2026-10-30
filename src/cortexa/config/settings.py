from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def load_env() -> None:
    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env", override=False)


@dataclass(frozen=True)
class LLMSettings:
    provider: str = ""
    temperature: float = 0.2


def get_llm_settings() -> LLMSettings:
    provider = os.getenv("LLM_PROVIDER", "")
    return LLMSettings(provider=provider)


def feature_flag(name: str, default: bool = False) -> bool:
    """Read config.yaml features.<name>; missing file/parse failure → default."""
    import yaml

    path = Path(__file__).resolve().parents[3] / "config.yaml"
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return default
    value = (config.get("features") or {}).get(name)
    return default if value is None else bool(value)
