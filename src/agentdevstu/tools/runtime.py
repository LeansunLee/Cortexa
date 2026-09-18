"""Shared tool-calling safeguards for grounded business-data answers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


DATA_QUERY_GROUNDING_FAILURE = (
    "本轮已匹配到可用的数据查询能力，但模型没有成功发起查询，因此无法提供可靠的业务数据。"
    "请重试；系统不会使用历史回答或模型推测补写结果。"
)


def bind_tools_for_first_response(model: Any, tools: Sequence[Any], required_tools: Sequence[Any]):
    """Bind tools for the first model turn.

    When required_tools are specified, expose only those tools to guide the model
    toward calling the right one. Does not use tool_choice="required" because
    some models (e.g. 小米mimo) don't handle forced tool calling well.
    """
    if required_tools:
        # Expose only matched business tools on the forced turn. Otherwise an
        # unrelated optional tool could satisfy the provider's requirement.
        return model.bind_tools(list(required_tools))
    return model.bind_tools(list(tools))


def called_required_tool(response: Any, required_tools: Sequence[Any]) -> bool:
    """Return whether the response called one of the required business tools."""
    if not required_tools:
        return True
    required_names = {str(tool.name) for tool in required_tools}
    return any(
        call.get("name") in required_names
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
