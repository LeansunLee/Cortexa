from __future__ import annotations

from typing import Annotated, Any, Literal

from langgraph.graph import add_messages
from pydantic import BaseModel, Field


class AgentState(BaseModel):
    goal: str = ""
    active_agent: Literal["researcher", "writer", "supervisor", "finish"] = "researcher"
    messages: Annotated[list[Any], add_messages] = Field(default_factory=list)
    draft: str = ""
    notes: str = ""
    iterations: int = 0
    max_iterations: int = 4
    research_context: str = ""
