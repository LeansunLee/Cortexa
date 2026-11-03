"""Shared tool-calling safeguards for grounded business-data answers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


DATA_QUERY_GROUNDING_FAILURE = (
    "本轮已匹配到可用的数据查询能力，但模型没有成功发起查询，因此无法提供可靠的业务数据。"
    "请重试；系统不会使用历史回答或模型推测补写结果。"
)


_TEXT_TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>\s*<function\s*=\s*([A-Za-z0-9_\-\.]+)\s*>(.*?)</function>\s*</tool_call>",
    re.S,
)
_TEXT_TOOL_CALL_PARAM_RE = re.compile(
    r"<parameter\s*=\s*([A-Za-z0-9_\-]+)\s*>(.*?)</parameter>",
    re.S,
)
_TOOL_CALL_SENTINEL = "<tool_call"


def parse_text_tool_calls(content: str) -> list[dict]:
    """Parse tool calls the model emitted as plain-text markup instead of the
    provider's structured tool_calls (some models do this under prompt drift).

    Recognizes the observed ``<tool_call><function=name><parameter=k>v</parameter>``
    format. Returns langchain-style ``{"name", "args", "id"}`` dicts.
    """
    calls = []
    for index, match in enumerate(_TEXT_TOOL_CALL_BLOCK_RE.finditer(content or "")):
        name = match.group(1).strip()
        args = {}
        for param in _TEXT_TOOL_CALL_PARAM_RE.finditer(match.group(2)):
            args[param.group(1).strip()] = param.group(2)
        calls.append({"name": name, "args": args, "id": f"text_call_{index}"})
    return calls


def strip_text_tool_markup(content: str) -> str:
    """Remove tool-call markup blocks from text, returning the remaining prose."""
    cleaned = _TEXT_TOOL_CALL_BLOCK_RE.sub("", content or "")
    # An unterminated block would still leak; cut from the sentinel onward.
    start = cleaned.find(_TOOL_CALL_SENTINEL)
    if start != -1:
        cleaned = cleaned[:start]
    return cleaned.strip()


def promote_text_tool_calls(response: Any, tools: Sequence[Any]):
    """Upgrade a plain-text tool-call response into structured tool_calls.

    Returns the response unchanged when it already has structured tool_calls or
    its content carries no recognizable markup. When the markup names an unknown
    tool, the markup is stripped and the remaining prose kept as content so raw
    protocol text never reaches the user.
    """
    content = getattr(response, "content", None)
    if getattr(response, "tool_calls", None):
        return response
    if isinstance(content, list):
        content = "".join(block if isinstance(block, str) else block.get("text", "") for block in content)
    if not content or _TOOL_CALL_SENTINEL not in content:
        return response
    known = {str(tool.name) for tool in tools or []}
    calls = [call for call in parse_text_tool_calls(content) if call["name"] in known]
    cleaned = strip_text_tool_markup(content)
    if calls:
        try:
            from langchain_core.messages import AIMessage

            return AIMessage(
                content="",
                tool_calls=[{"name": c["name"], "args": c["args"], "id": c["id"]} for c in calls],
            )
        except Exception:
            pass
    try:
        response.content = cleaned
    except Exception:
        from langchain_core.messages import AIMessage

        response = AIMessage(content=cleaned)
    return response


class MarkupGuard:
    """Hold back streamed tokens that may be the start of tool-call markup so
    protocol text never reaches the user before we know how to route it."""

    def __init__(self, sentinel: str = _TOOL_CALL_SENTINEL):
        self.sentinel = sentinel
        self.suppressed = False
        self.buffered = ""
        self._pending = ""

    def feed(self, token: str) -> str:
        """Return the text that is safe to emit now."""
        if self.suppressed:
            self.buffered += token
            return ""
        pending = self._pending + token
        if self.sentinel in pending:
            index = pending.index(self.sentinel)
            self.suppressed = True
            self.buffered = pending[index:]
            self._pending = ""
            return pending[:index]
        keep = 0
        for k in range(min(len(pending), len(self.sentinel) - 1), 0, -1):
            if self.sentinel.startswith(pending[-k:]):
                keep = k
                break
        emitted = pending[: len(pending) - keep] if keep else pending
        self._pending = pending[len(pending) - keep:] if keep else ""
        return emitted

    def flush(self) -> str:
        """Return any held-back text once the response is known markup-free."""
        pending, self._pending = self._pending, ""
        return pending


def bind_tools_for_first_response(model: Any, tools: Sequence[Any], required_tools: Sequence[Any]):
    """Bind tools for the first model turn.

    When required_tools are specified, expose only those tools to guide the model
    toward calling the right one. Does not use tool_choice="required" because
    some models (e.g. 小米mimo) don't handle forced tool calling well.
    """
    if required_tools:
        # Expose only matched business tools on the forced turn. Otherwise an
        # unrelated optional tool could satisfy the provider's requirement.
        return model.bind_tools([*required_tools, *[tool for tool in tools if tool.name == "ask_user"]])
    return model.bind_tools(list(tools))


def called_required_tool(response: Any, required_tools: Sequence[Any]) -> bool:
    """Return whether the response called one of the required business tools."""
    if not required_tools:
        return True
    required_names = {str(tool.name) for tool in required_tools}
    return any(
        call.get("name") in required_names or call.get("name") == "ask_user"
        for call in (getattr(response, "tool_calls", None) or [])
    )



def should_require_business_tool(query: str | None, business_tools: Sequence[Any]) -> bool:
    """Return whether this turn should be grounded by a configured business-data tool.

    The check is intentionally broad and tool-agnostic: if the user appears to
    ask for records, facts, counts, lists, statuses, metrics, or verification
    and the agent has business data tools, the first model turn must call one
    of those tools. Routine chat and text-only rewriting should remain direct.
    """
    if not business_tools:
        return False
    import re

    text = re.sub(r"@[^\s@]+", "", query or "").strip()
    if not text:
        return False
    if re.search(
        r"^(?:谢谢|多谢|好的|好|明白|收到|了解|你好|您好|早上好|晚上好|继续[。！!]?\s*$|"
        r"(?:请)?(?:把|将)?(?:上面|上述|刚才|这段|已有|以上).*(?:总结|改写|翻译|整理|缩短|润色)|"
        r"(?:请)?(?:改写|翻译|润色|总结一下))",
        text,
        re.I,
    ):
        return False
    if re.search(r"不要查询|不用查询|无需查询|不要查库|不用查库|不要调用工具|不用工具", text):
        return False
    # Meta questions about the data itself (provenance, freshness, trust) ask for
    # an explanation, not a new query; forcing a tool call only gets the model
    # replaced by the grounding-failure notice. Real queries that also mention
    # provenance still fall through to the action verbs below.
    if re.search(
        r"来源|出处|哪(里|儿)?来的?|可信|靠谱|准不准|准确(吗|性)|时效|滞后|更新时间|更新频率|多久更新|爬虫|爬取|最新",
        text,
    ) and not re.search(
        r"查询|查一下|查下|查找|检索|列出|列表|统计|汇总|筛选|有哪些|多少|几(个|家|条)?|对比",
        text,
    ):
        return False
    action_pattern = (
        r"查询|查一下|查下|查找|检索|搜索|筛选|列出|列表|明细|有哪些|多少|几(个|家|条)?|"
        r"统计|汇总|核实|确认|给我|帮我看|看一下|看下"
    )
    if re.search(action_pattern, text, re.I):
        return True

    # Generic noun-only follow-ups such as "有哪些..." may omit the capability
    # name. Use configured tool descriptions as vocabulary instead of hardcoding
    # any domain entities or enum values.
    vocab_parts = []
    for tool in business_tools:
        for attr in ("name", "description"):
            value = getattr(tool, attr, "") or ""
            vocab_parts.extend(re.findall(r"[一-鿿A-Za-z0-9_]{2,}", str(value)))
    vocab = {part for part in vocab_parts if part not in {"查询", "数据能力", "工具", "状态", "数量", "总数", "结果"}}
    return any(part in text for part in vocab)
