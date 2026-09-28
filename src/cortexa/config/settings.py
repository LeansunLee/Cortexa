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
