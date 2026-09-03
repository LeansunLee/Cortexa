from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, StateGraph

from agentdevstu.agents.agents import (
    researcher_node,
    supervisor_node,
    writer_node,
)
from agentdevstu.workflow.schema import AgentState


def route_after_supervisor(state: AgentState) -> Literal["writer", "__end__"]:
    if state.active_agent == "finish":
        return "__end__"
    return "writer"


def build_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer", writer_node)
    graph.add_node("supervisor", supervisor_node)

    graph.set_entry_point("researcher")
    graph.add_edge("researcher", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"writer": "writer", "__end__": END},
    )
    graph.add_edge("writer", END)

    return graph.compile()
