"""Capability descriptions and deterministic matching, separate from execution rights."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class CapabilityType(StrEnum):
    TOOL = "TOOL"
    DATA = "DATA"
    KNOWLEDGE = "KNOWLEDGE"
    MEMORY = "MEMORY"
    WEB = "WEB"
    AGENT = "AGENT"
    HUMAN = "HUMAN"
    ROBOT = "ROBOT"
    SENSOR = "SENSOR"


class CapabilityDescriptor(BaseModel):
    id: str
    workspace_id: str
    name: str
    type: CapabilityType
    description: str = ""
    operations: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    permission: str = "revalidate_at_executor"
    risk_level: Literal["low", "high", "unknown"] = "unknown"
    requires_confirmation: bool = True
    context_policy: dict[str, Any] = Field(default_factory=dict)
    input_budget: int | None = Field(default=None, gt=0)
    timeout: float | None = Field(default=None, gt=0)


@dataclass(frozen=True)
class MatchScope:
    """Server-derived authorization snapshot. Never construct from a client ID list."""

    workspace_id: str
    allowed_ids: frozenset[str]


@dataclass(frozen=True)
class CapabilityMatch:
    capability: CapabilityDescriptor
    score: int
    reasons: tuple[str, ...]


def _terms(text: str) -> set[str]:
    # Bounded lexical overlap works without a model, vector store or domain dictionary.
    text = text[:8000].casefold()
    terms = set(re.findall(r"[a-z0-9_]{2,}", text))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        terms.update(phrase[i : i + 2] for i in range(len(phrase) - 1))
    return terms


def match_capabilities(
    query: str,
    candidates: list[CapabilityDescriptor],
    scope: MatchScope,
    *,
    operations: tuple[str, ...] = (),
    types: tuple[CapabilityType, ...] = (),
    top_k: int = 5,
) -> list[CapabilityMatch]:
    """Filter before scoring. A match is a candidate, never an invocation authorization."""
    if top_k <= 0 or not scope.workspace_id:
        return []
    words = _terms(query)
    found = {}
    for cap in candidates:
        if (
            cap.workspace_id != scope.workspace_id
            or cap.id not in scope.allowed_ids
            or cap.availability != "available"
            or cap.type in {CapabilityType.HUMAN, CapabilityType.ROBOT, CapabilityType.SENSOR}
            or types
            and cap.type not in types
        ):
            continue
        overlap = words & _terms(" ".join([cap.name, *cap.aliases, *cap.domains]))
        description = words & _terms(cap.description)
        operation = set(operations) & set(cap.operations)
        score = len(overlap) * 3 + len(description) + len(operation) * 2
        if score:
            reasons = tuple(
                name
                for name, value in (
                    ("name_alias_domain", overlap),
                    ("description", description),
                    ("operation", operation),
                )
                if value
            )
            match = CapabilityMatch(cap, score, reasons)
            if cap.id not in found or score > found[cap.id].score:
                found[cap.id] = match
    return sorted(found.values(), key=lambda match: (-match.score, match.capability.id))[: min(top_k, 20)]
