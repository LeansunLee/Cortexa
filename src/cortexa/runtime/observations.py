"""Lossless in-process results; trace projection deliberately excludes result content."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .capabilities import CapabilityType


class ObservationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    NOT_READY = "NOT_READY"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


@dataclass
class Observation:
    source_type: CapabilityType
    source_id: str
    action_id: str
    status: ObservationStatus
    summary: str = ""
    facts: list[Any] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)
    confidence: float | None = None
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Never automatically serialize arbitrary ORM results, credentials or large payloads.
    raw_result: Any = field(default=None, repr=False)
