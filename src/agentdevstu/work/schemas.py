import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=4000)
    deliverable_requirement: str = Field(default="", max_length=2000)
    assignee_type: Literal["human", "agent"] = "human"
    assignee_id: uuid.UUID
    reviewer_id: uuid.UUID | None = None
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("截止时间必须包含时区")
        return value


class ReviewInput(BaseModel):
    comment: str = Field(default="", max_length=2000)


class ExtractInput(BaseModel):
    message_id: uuid.UUID


class MemoryInput(BaseModel):
    memory_kind: Literal["fact", "preference", "relationship", "decision", "event", "observation", "outcome", "concern", "other"] | None = None
    deliverable_id: uuid.UUID | None = None
    agent_id: uuid.UUID
    type: Literal["semantic", "episodic", "focus"] = "semantic"
    content: str = Field(min_length=1, max_length=2000)


class KnowledgeInput(BaseModel):
    knowledge_base_id: uuid.UUID


class WorkLogInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=2000)


class WorkLogUpdate(WorkLogInput):
    version: int = Field(ge=1)
