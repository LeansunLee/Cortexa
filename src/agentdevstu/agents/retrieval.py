import asyncio
from collections import Counter
import json
import re
from dataclasses import dataclass

from agentdevstu.agents.prompts import reference_message


@dataclass(frozen=True)
class RetrievalPlan:
    web: bool = False
    knowledge: bool = False
    memory: bool = False
    data: bool = False
    followup: bool = False
    reason: str = "复用当前对话，无需检索"


def plan_retrieval(query, recent_messages=None):
    text = re.sub(r"@[^\s@]+", "", query).strip()
    web = bool(re.search(r"网上|联网|全网|互联网|网页|官网|公开信息|DuckDuckGo|网络搜索|搜索引擎|媒体评测|最新新闻|web search", text, re.I))
    if re.search(r"不要联网|无需联网|不用联网|禁止联网|不要搜索|不用搜索", text):
        web = False
    internal = bool(re.search(r"内部|知识库|公司政策|销售政策|制度|文档|资料库", text))
    reuse = bool(re.search(r"^(?:谢谢|好的|明白|你好|收到|继续[。！!]?\s*$|(?:请)?(?:把|将)?(?:上面|上述|刚才|这段|已有|以上).*(?:总结|改写|翻译|整理|缩短|润色)|(?:请)?(?:改写|翻译|润色|总结一下))", text))
    refresh = bool(re.search(r"重新查询|刷新|最新|重新检索", text))
    if reuse and not refresh and not web:
        return RetrievalPlan()
    if web:
        return RetrievalPlan(web=True, knowledge=internal, reason="联网搜索" + ("并结合明确要求的内部资料" if internal else "；不检索内部知识，数据工具遵守用户来源限制"))
    if not text:
        return RetrievalPlan()
    return RetrievalPlan(knowledge=True, memory=True, reason="检索相关知识与记忆")


def select_capabilities(items, query=None):
    """Expose configured capabilities; the model selects using descriptions and context.

    Do not prefilter by vocabulary, language, name overlap or an arbitrary top K.
    """
    return list(items)


def _result_facets(data, max_values=30):
    """Build exact counts for low-cardinality columns in structured results."""
    if not data or not all(isinstance(row, dict) for row in data):
        return {}
    columns = list(dict.fromkeys(key for row in data for key in row))
    facets = {}
    for column in columns:
        counts = Counter("（空）" if row.get(column) is None else str(row.get(column)) for row in data)
        if 0 < len(counts) <= max_values:
            facets[column] = dict(counts)
    return facets


def bounded_result(result, max_rows=1000, max_chars=120000):
    if not isinstance(result, dict):
        return {"preview": str(result)[:max_chars], "truncated": len(str(result)) > max_chars}
    data = result.get("data")
    if not isinstance(data, list):
        encoded = json.dumps(result, ensure_ascii=False, default=str)
        return result if len(encoded) <= max_chars else {"preview": encoded[:max_chars], "truncated": True}
    rows = []
    for row in data[:max_rows]:
        if len(json.dumps(rows + [row], ensure_ascii=False, default=str)) > max_chars:
            break
        rows.append(row)
    truncated = len(rows) < len(data)
    return {
        "data": rows,
        "row_count": result.get("row_count", len(data)),
        "returned_rows": len(rows),
        "truncated": truncated,
        "facets": _result_facets(data),
        "notice": (
            "返回受限的查询结果；不得把样本行数当作业务总数。需要更多明细请缩小筛选范围。"
            if truncated else
            "已返回本次查询取得的全部数据行；字段名和值必须原样使用，不得补写未返回字段。分组数量必须使用 facets，不得自行数行推算。"
        ),
    }


async def web_reference(query):
    from agentdevstu.tools.search import search_web
    public_query = re.split(r"[，,；;]|并结合|结合内部|再结合", query, maxsplit=1)[0]
    public_query = re.sub(r"@[^\s@]+", "", public_query).strip()[:200]
    try:
        results = await asyncio.wait_for(asyncio.to_thread(search_web, public_query, max_results=5), timeout=25)
        if not results:
            return reference_message("联网搜索状态", "DuckDuckGo 未返回可用结果；不能声称已核实网上信息，也不要用内部资料冒充网上结果。"), [], "未返回可用结果"
        sources = [{"type": "web", "name": item["title"], "url": item["url"], "description": item["snippet"][:700]} for item in results]
        return reference_message("联网搜索结果", sources), sources, f"找到 {len(sources)} 条网页结果"
    except Exception:
        return reference_message("联网搜索状态", "DuckDuckGo 请求失败或超时，本轮未取得网页结果。请如实说明，不能声称已完成联网核实。"), [], "搜索失败或超时"


def history_text(content, limit=4000):
    if len(content) <= limit:
        return content
    return content[:limit // 2] + "\n[历史消息中段因长度预算省略]\n" + content[-limit // 2:]


def limited_history(messages, max_chars=18000):
    selected = []
    consumed = 0
    for message in reversed(list(messages)):
        size = min(len(message.content), 4000)
        if consumed + size > max_chars:
            break
        selected.append(message)
        consumed += size
    return list(reversed(selected))
