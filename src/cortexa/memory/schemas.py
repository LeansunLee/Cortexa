"""Validated domain inputs shared by governance and API adapters."""

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryType = Literal["semantic", "episodic", "focus"]
MemoryKind = Literal[
    "fact", "preference", "relationship", "decision", "event", "observation", "outcome", "concern", "other"
]


class Candidate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", allow_inf_nan=False)
    type: MemoryType = "semantic"
    content: str = Field(min_length=1, max_length=2000)
    memory_kind: MemoryKind | None = None
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    subject_type: str | None = Field(default=None, max_length=64)
    subject_id: str | None = Field(default=None, max_length=128)
    subject_name: str | None = Field(default=None, max_length=255)
    claim_key: str | None = Field(default=None, max_length=255)
    source_mode: Literal["explicit", "system", "inferred"] = "inferred"
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    expires_at: datetime | None = None
    risk_level: Literal["unknown", "none", "low", "high"] = "unknown"
    worth_remembering: bool = True
    responsibility_match: bool = True

    @field_validator("occurred_at", "valid_from", "valid_to", "expires_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("时间必须包含时区；未知时间请留空")
        return value.astimezone(timezone.utc) if value else value

    @model_validator(mode="after")
    def interval(self):
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class Correction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=1000)
    new_content: str | None = Field(default=None, min_length=1, max_length=2000)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    _aware = field_validator("valid_from", "valid_to")(Candidate.aware.__func__)
    _interval = model_validator(mode="after")(Candidate.interval)


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    top_k: int = Field(default=5, ge=1, le=10)
    token_budget: int = Field(default=1200, ge=200, le=2400)
    candidate_limit: int = Field(default=200, ge=20, le=500)
    relevance_threshold: float = Field(default=0.2, ge=0.05, le=0.9)
    focus_boost: float = Field(default=0.1, ge=0, le=0.1)
    semantic_judgment: bool = True
    extract_limit: int = Field(default=5, ge=1, le=5)
