from __future__ import annotations
from agentdevstu.usage.context import usage_action, annotate_usage

import json
from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agentdevstu.tools.rag import retrieve
from agentdevstu.tools.search import search_web
from agentdevstu.workflow.schema import AgentState

_SYSTEM_PROMPTS = {
    "researcher": (
        "You are a concise research assistant. "
        "Collect facts and write short notes. "
        "Reply in the same language as the user's goal. "
        "Keep it under 200 words."
    ),
    "writer": (
        "You are a concise writer. "
        "Turn research notes into a short draft. "
        "Reply in the same language as the goal. "
        "Keep it under 300 words."
    ),
    "supervisor": (
        "You are the supervisor. "
        'Decide next step as JSON: {"next": "writer"} or {"next": "finish"}. '
        "Choose finish if notes exist. Choose writer if no draft yet."
    ),
}

_SIMPLE_KEYWORDS = {"你好", "你是谁", "hi", "hello", "who", "介绍", "介绍一下"}


def _is_simple_goal(goal: str) -> bool:
    lower = goal.lower().strip()
    return any(kw in lower for kw in _SIMPLE_KEYWORDS) and len(lower) < 30


def _build_messages(
    state: AgentState,
    role: Literal["researcher", "writer", "supervisor"],
) -> Sequence[SystemMessage | HumanMessage]:
    msgs: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=_SYSTEM_PROMPTS[role])
    ]
    parts = [f"Goal: {state.goal}"]
    if state.notes:
        parts.append(f"Notes:\n{state.notes}")
    if state.draft:
        parts.append(f"Draft:\n{state.draft}")
    msgs.append(HumanMessage(content="\n\n".join(parts)))
    return msgs


def _extract_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


@usage_action("research", source="workflow")
def researcher_node(state: AgentState) -> dict[str, Any]:
    llm = _get_model()
    response = llm.invoke(_build_messages(state, "researcher"))
    text = _extract_text(response)

    notes = state.notes
    if text.strip():
        notes = (notes + "\n" + text).strip() if notes else text

    research_context = text

    if not _is_simple_goal(state.goal):
        try:
            search_results = search_web(state.goal[:80], max_results=2)
            research_context += "\n\nSearch: " + json.dumps(
                search_results, ensure_ascii=False
            )[:300]
        except Exception:
            pass

        try:
            rag_results = retrieve(state.goal[:80], top_k=2)
            research_context += "\n\nRAG: " + json.dumps(
                rag_results, ensure_ascii=False
            )[:300]
        except Exception:
            pass

    return {
        "notes": notes,
        "research_context": research_context,
        "iterations": state.iterations + 1,
        "messages": [
            response,
            ToolMessage(content=research_context[:500], tool_call_id="tools"),
        ],
        "active_agent": "supervisor",
    }


@usage_action("writing", source="workflow")
def writer_node(state: AgentState) -> dict[str, Any]:
    llm = _get_model()
    response = llm.invoke(_build_messages(state, "writer"))
    text = _extract_text(response)

    draft = state.draft
    if text.strip():
        draft = (draft + "\n" + text).strip() if draft else text

    return {
        "draft": draft,
        "iterations": state.iterations + 1,
        "messages": [response],
        "active_agent": "supervisor",
    }


@usage_action("supervision", source="workflow")
def supervisor_node(state: AgentState) -> dict[str, Any]:
    llm = _get_model()
    response = llm.invoke(_build_messages(state, "supervisor"))
    text = _extract_text(response)

    next_agent: Literal["writer", "finish"] = "finish"
    try:
        payload = json.loads(text)
        choice = str(payload.get("next", "finish"))
        if choice in {"writer", "finish"}:
            next_agent = choice  # type: ignore[assignment]
    except Exception:
        if state.notes and not state.draft:
            next_agent = "writer"

    if state.iterations >= state.max_iterations:
        next_agent = "finish"

    return {
        "iterations": state.iterations + 1,
        "messages": [response],
        "active_agent": next_agent,
    }


def _get_model() -> Any:
    from langchain_core.runnables import RunnableLambda

    from agentdevstu.config.llm_providers import create_llm
    from agentdevstu.config.settings import load_env

    load_env()
    try:
        return create_llm()
    except Exception:
        pass

    def local_responder(messages: Any) -> AIMessage:
        last = messages[-1].content if messages else ""
        if isinstance(last, list):
            last = " ".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in last
            )
        text = str(last)
        if "research" in text.lower() or "goal" in text.lower():
            return AIMessage(
                content="Collected facts: LangGraph supports stateful agent workflows"
                " with tools, memory, and human oversight."
            )
        return AIMessage(
            content="Draft created: LangGraph is a strong choice for multi-agent apps"
            " because it supports state, tools, and human-in-the-loop."
        )

    return RunnableLambda(local_responder)
