import re
import uuid
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select

# BENDA product families used for diversity-aware document selection.
PRODUCT_FAMILIES = ["灰石", "金吉拉", "拿破仑", "黑旗", "黑骑"]
STOP_CHARS = set("的了在是我有和就不人都上也很到说要去你会着没有看好这他她它们那请问可以能吗呢吧啊哦嗯啦嘛呀哇")

# Two-stage retrieval: stage 1 locates documents by the summary stored in
# ``Document.content`` (LLM generated at upload time), stage 2 extracts
# relevant passages from the full text kept on the filesystem. MAX_DOCS
# bounds the context budget; raise it together with a token budget check.
MAX_DOCS = max(1, min(int(os.getenv("KNOWLEDGE_MAX_DOCS", "10")), 50))
MAX_PER_FAMILY_WITHOUT_FOCUS = 2
FULL_CONTENT_LIMIT = 10000
WINDOW_SIZE = 1200
WINDOW_STEP = 1000
MAX_WINDOWS = 5


def _build_query_context(query_text: str) -> dict:
    try:
        import jieba

        keywords = [w.strip() for w in jieba.lcut(query_text.lower()) if w.strip() and len(w.strip()) > 1]
    except ImportError:
        keywords = []
    keywords = [t for t in keywords if not all(c in STOP_CHARS for c in t)]
    return {
        "keywords": keywords,
        "normalized": re.sub(r"\s+", "", query_text.lower()),
        "families": [f for f in PRODUCT_FAMILIES if f in query_text],
        "mentions": [
            re.sub(r"\s+", "", value).lower()
            for value in re.findall(r"(?:灰石|金吉拉|拿破仑|黑旗|黑骑)\s*\d+", query_text)
        ],
    }


def _score_text(doc_name: str, text: str, ctx: dict) -> int:
    """Score a text (summary or full content) against the parsed query.

    Mirrors the legacy scoring: jieba keyword hits, space-normalized
    substring matching, product-family bonus and title product bonus.
    """
    haystack = (doc_name + "\n" + (text or "")).lower()
    jieba_score = sum(2 for kw in ctx["keywords"] if kw in haystack)
    normalized_haystack = re.sub(r"\s+", "", haystack)
    query_no_space = ctx["normalized"]
    normalized_score = 0
    if len(query_no_space) >= 3:
        if query_no_space in normalized_haystack:
            normalized_score = 10
        else:
            # Longest matching segment first; shorter segments cannot win.
            for seg_len in range(min(len(query_no_space), 10), 2, -1):
                if any(
                    query_no_space[start:start + seg_len] in normalized_haystack
                    for start in range(len(query_no_space) - seg_len + 1)
                ):
                    normalized_score = seg_len
                    break
    family_bonus = 0
    for family in PRODUCT_FAMILIES:
        if family in haystack[:200]:
            if family in ctx["families"]:
                family_bonus = 5
            elif not ctx["families"]:
                family_bonus = 1
    title_bonus = 20 if any(value in re.sub(r"\s+", "", doc_name.lower()) for value in ctx["mentions"]) else 0
    return jieba_score + normalized_score + family_bonus + title_bonus


async def retrieve_knowledge(agent, query_text: str, db, sources: list | None = None, stats: dict | None = None) -> str:
    """Retrieve relevant knowledge in two stages.

    Stage 1 locates candidate documents by matching the query against the
    document summary in ``Document.content`` without touching the filesystem.
    Stage 2 loads the full text of the selected documents and extracts the
    most relevant passages. When no summary matches, fall back to a legacy
    full-text scan so keyword-shaped queries never miss.
    """
    from cortexa.agents.retrieval import plan_retrieval

    if not plan_retrieval(query_text).knowledge:
        return ""

    if not query_text or not query_text.strip():
        return ""

    from sqlalchemy import and_, or_

    from cortexa.data.doc_storage import load_document_content
    from cortexa.db.models import Document, KnowledgeBase

    bound_ids = []
    for kb_id in agent.knowledge_base_ids or []:
        try:
            bound_ids.append(uuid.UUID(str(kb_id)))
        except (ValueError, TypeError):
            continue
    result = await db.execute(
        select(Document).join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.workspace_id == agent.workspace_id,
            KnowledgeBase.status == "active",
            or_(
                KnowledgeBase.agent_id == agent.id,
                and_(KnowledgeBase.agent_id.is_(None), KnowledgeBase.id.in_(bound_ids)),
            ),
            Document.status == "active",
            or_(
                Document.valid_until.is_(None),
                Document.valid_until >= datetime.now(ZoneInfo("Asia/Shanghai")).date(),
            ),
        )
    )
    all_docs = list(result.scalars().all())

    if not all_docs:
        return ""

    ctx = _build_query_context(query_text)

    def name_matches(doc) -> bool:
        lowered = doc.name.lower()
        return any(token in lowered for token in ctx["keywords"]) or any(f in doc.name for f in ctx["families"])

    processing: list[str] = []
    unreadable: list[str] = []
    readable = []
    for doc in all_docs:
        metadata = doc.metadata_json or {}
        summary = doc.content or ""
        if not summary.strip() or metadata.get("encoding") == "base64" or summary.startswith("JVBER"):
            if name_matches(doc):
                bucket = processing if metadata.get("extraction_status") in {"pending", "processing"} else unreadable
                bucket.append(doc.name)
            continue
        readable.append(doc)

    full_texts: dict[str, str] = {}

    def load_full(doc) -> str:
        key = str(doc.id)
        if key not in full_texts:
            full_texts[key] = load_document_content(key) or doc.content or ""
        return full_texts[key]

    from starlette.concurrency import run_in_threadpool
    from cortexa.rag.document_selection import rank_documents
    for doc in readable:
        await run_in_threadpool(load_full, doc)
    scored = await run_in_threadpool(rank_documents, readable, query_text, full_texts)

    # Diversity: cap how many documents of the same product family are kept.
    max_per_family = MAX_DOCS if ctx["families"] else MAX_PER_FAMILY_WITHOUT_FOCUS
    family_counts: dict[str, int] = {}
    top_docs = []
    for score, doc in scored:
        if len(top_docs) >= MAX_DOCS:
            break
        family = next((f for f in PRODUCT_FAMILIES if f in doc.name), "")
        count = family_counts.get(family, 0)
        if family and count >= max_per_family:
            continue
        family_counts[family] = count + 1
        top_docs.append((score, doc))
    # Diversity changes ordering, not coverage when the context budget remains.
    selected_ids = {str(doc.id) for _, doc in top_docs}
    for item in scored:
        if len(top_docs) >= MAX_DOCS:
            break
        if str(item[1].id) not in selected_ids:
            top_docs.append(item)
            selected_ids.add(str(item[1].id))
    retrieval_stats = {'matched_count': len(scored), 'selected_count': len(top_docs),
                       'truncated': len(scored) > len(top_docs)}
    if stats is not None:
        stats.update(retrieval_stats, pending_count=len(processing), unreadable_count=len(unreadable))

    # Stage 2: extract relevant passages from each selected document.
    context_parts = []
    for _, doc in top_docs:
        full_content = load_full(doc)
        # Preserve short policies in full; for long manuals select relevant
        # windows throughout the document instead of always truncating after
        # page one.
        if len(full_content) <= FULL_CONTENT_LIMIT:
            content_preview = full_content
        else:
            windows = [(start, full_content[start:start + WINDOW_SIZE]) for start in range(0, len(full_content), WINDOW_STEP)]
            ranked = sorted(windows, key=lambda item: _score_text(doc.name, item[1], ctx), reverse=True)
            chosen = sorted(ranked[:MAX_WINDOWS], key=lambda item: item[0])
            content_preview = "\n[节选]\n".join(text for _, text in chosen)
        context_parts.append(f"### {doc.name}\n{content_preview}")
        if sources is not None:
            sources.append({
                "type": "knowledge_base",
                "name": doc.name,
                "id": str(doc.knowledge_base_id),
                "document_id": str(doc.id),
                "description": content_preview,
                "doc_count": 1,
                **retrieval_stats,
            })
    if processing:
        context_parts.append("### 文档正在识别\n" + "\n".join(processing)
                             + "\n这些文档已上传，系统正在进行文字识别。请告知用户稍后重试，无需重新上传；不得编造尚未识别的内容。")
    if unreadable:
        context_parts.append(
            "### 相关文件读取失败\n以下文件存在于可访问的知识库，但没有可读取的正文：\n"
            + "\n".join(f"- {name}" for name in unreadable)
            + "\n请告知用户需要补充可提取文字的原文件或 OCR 文本；不得据文件名或历史回复编造政策内容。"
        )
    return "\n\n".join(context_parts)
