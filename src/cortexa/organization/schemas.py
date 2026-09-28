import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class UnitInput(Input):
    name: str = Field(min_length=1, max_length=120)
    code: str | None = Field(default=None, max_length=80)
    parent_id: uuid.UUID | None = None
    type: Literal["department", "team"] = "department"
    manager_user_id: uuid.UUID | None = None
    sort_order: int = Field(default=0, ge=0, le=100000)
    status: Literal["active", "disabled"] = "active"

    @field_validator("code")
    @classmethod
    def empty_code(cls, value):
        return value or None


class ProfileInput(Input):
    org_unit_id: uuid.UUID | None = None
    position_title: str = Field(default="", max_length=120)
    responsibility: str = Field(default="", max_length=2000)
    responsibility_tags: list[str] = Field(default_factory=list, max_length=30)
    coverage_scope: str = Field(default="", max_length=1000)

    @field_validator("responsibility_tags")
    @classmethod
    def tags(cls, values):
        result = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 40:
                raise ValueError("职责标签须为 1–40 个字符")
            if value not in result:
                result.append(value)
        return result


class RecommendationInput(Input):
    title: str = Field(default="", max_length=200)
    goal: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=4000)
    deliverable_requirement: str = Field(default="", max_length=2000)
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
