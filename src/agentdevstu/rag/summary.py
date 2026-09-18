"""LLM-generated document summaries for knowledge base retrieval.

The database stores a retrieval-oriented summary in ``Document.content``
while the full text stays on the filesystem. Retrieval first locates
documents by summary, then extracts passages from the full text.
"""

from __future__ import annotations
from agentdevstu.usage.context import usage_action, annotate_usage

import asyncio

# Keep the LLM input bounded: head plus tail covers manuals whose
# beginning is a table of contents and whose tail holds appendices.
SUMMARY_MAX_INPUT_CHARS = 10000
SUMMARY_TAIL_CHARS = 2000
SUMMARY_TIMEOUT_SECONDS = 60
# Short documents are stored as their own summary; no LLM call is needed.
SUMMARY_FULL_TEXT_MAX_CHARS = 1000

DOC_SUMMARY_PROMPT = """你是知识库摘要助手。请为下面的文档生成一份用于后续关键词检索的中文摘要。

要求：
1. 直接输出摘要正文，不要标题、前言、解释或"摘要："等前缀。
2. 概括文档的主题和主要内容要点，覆盖文档的主要章节或主题。
3. 必须保留文中出现的关键检索词：产品名称、具体型号（含数字，如"金吉拉250""灰石300"）、部件与参数名称、政策/流程名称、重要的数字结论。
4. 长度控制在 300 字以内。
5. 只概括文档中真实存在的内容，不得编造；专有名词保持原文。

文档名：{name}

文档内容：
{content}"""


@usage_action("document_summary", source="knowledge")
async def generate_document_summary(doc_name: str, content: str) -> tuple[str, str]:
    """Generate a summary for a document.

    Returns ``(summary, source)`` where ``source`` is ``"llm"`` on success
    or ``"truncated"`` when the LLM failed and the legacy head-truncation
    summary from ``make_summary`` is used instead.
    """
    from agentdevstu.config.llm_providers import create_llm
    from agentdevstu.data.doc_storage import make_summary

    text = (content or "").strip()
    if not text:
        return "", "truncated"
    if len(text) <= SUMMARY_FULL_TEXT_MAX_CHARS:
        return text, "full"
    fallback = make_summary(text)
    sample = text[:SUMMARY_MAX_INPUT_CHARS]
    if len(text) > SUMMARY_MAX_INPUT_CHARS:
        sample += "\n…[中间内容省略]…\n" + text[-SUMMARY_TAIL_CHARS:]
    prompt = DOC_SUMMARY_PROMPT.format(name=doc_name, content=sample)
    try:
        model = create_llm()
        response = await asyncio.wait_for(
            model.ainvoke([{"role": "user", "content": prompt}]),
            timeout=SUMMARY_TIMEOUT_SECONDS,
        )
        raw = getattr(response, "content", "")
        summary = raw.strip() if isinstance(raw, str) else ""
        if summary:
            return summary, "llm"
        print(f"[DOC_SUMMARY] Empty summary for {doc_name}; using truncation fallback", flush=True)
    except Exception as error:
        print(f"[DOC_SUMMARY] LLM summary failed for {doc_name}: {type(error).__name__}: {error}", flush=True)
    return fallback, "truncated"
