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


async def retrieve_knowledge(agent, query_text: str, db, sources: list | None = None, stats: dict | None = None, *, context_budget: int = 6000) -> str:
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

    from cortexa.agents.retrieval import parse_knowledge_query
    from cortexa.rag.relevance import entity_relation
    analysis = parse_knowledge_query(query_text, all_docs)
    if not all_docs:
        if stats is not None:
            stats.update(matched_count=0, selected_count=0, direct_count=0,
                         evidence_status="EVIDENCE_INSUFFICIENT",
                         retrieval_trace={"query": query_text, "query_analysis": analysis.trace(),
                                          "candidate_count": 0, "ranking": [], "injected_context": "",
                                          "evidence_status": "EVIDENCE_INSUFFICIENT"})
        from cortexa.runtime.loop import token_upper_bound
        notice = "Evidence Insufficient：当前授权知识库中没有可用直接证据，不得编造目标事实或案例。"
        return notice if token_upper_bound(notice) <= context_budget else ""

    ctx = _build_query_context(query_text)

    def name_matches(doc) -> bool:
        lowered = doc.name.lower()
        if analysis.entities or analysis.ambiguous_entity:
            return entity_relation(doc, "", analysis)[0] == 'EXACT'
        return any(token in lowered for token in ctx["keywords"])

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
    from cortexa.rag.relevance import select_documents, passage_supports_entity, entity_key
    from cortexa.runtime.loop import token_upper_bound
    for doc in readable:
        await run_in_threadpool(load_full, doc)
    analysis, ranked = await run_in_threadpool(select_documents, readable, query_text, full_texts, analysis=analysis)
    eligible = [(decision, doc) for decision, doc in ranked if decision['eligible']]
    context_parts, injected = [], []
    targets = [entity_key(e) for e in analysis.entities]
    insufficient_notice = ('Evidence Insufficient：没有足够的直接证据支持目标事实；RELATED/BACKGROUND '
                           '只能作标注用途的参考，不能包装为真实事实或案例。')
    if targets:
        insufficient_notice += ' 未覆盖的核心实体：' + '、'.join(targets)
    notice_reserve = token_upper_bound(insufficient_notice) + 16
    # Evidence gate, then bounded injection. Top K is a ceiling, not a quota.
    reference_counts = {'RELATED': 0, 'BACKGROUND': 0}
    for decision, doc in eligible:
        if len(injected) >= MAX_DOCS:
            decision['filter_reasons'].append('top_k_ceiling')
            continue
        grade = decision['evidence_grade']
        if grade != 'DIRECT' and reference_counts[grade] >= 2:
            decision['filter_reasons'].append('reference_limit')
            continue
        full_content = load_full(doc)
        if len(full_content) <= FULL_CONTENT_LIMIT:
            previews = [full_content]
        else:
            windows = [(start, full_content[start:start + WINDOW_SIZE])
                       for start in range(0, len(full_content), WINDOW_STEP)]
            ranked_windows = sorted(windows, key=lambda item: _score_text(doc.name, item[1], ctx), reverse=True)
            chosen = sorted(ranked_windows[:MAX_WINDOWS], key=lambda item: item[0])
            previews = ['\n[节选]\n'.join(text for _, text in chosen)]
        # Reuse existing passage windows, explicitly labelled as excerpts;
        # try the strongest windows first when the complete document cannot fit.
        if token_upper_bound(previews[0]) > context_budget:
            candidates = [full_content[i:i + WINDOW_SIZE]
                          for i in range(0, len(full_content), WINDOW_STEP)]
            candidates.sort(key=lambda text: _score_text(doc.name, text, ctx), reverse=True)
            previews += ['[预算节选；未提供全文]\n' + text for text in candidates]
        selected_preview = None
        for preview in previews:
            if grade == 'DIRECT' and not passage_supports_entity(preview, analysis):
                continue
            description = f"[{grade}] {decision['purpose']}\n{preview}"
            block = f"### {doc.name}\n{description}"
            # Reserve room for the mandatory evidence-status notice.
            if token_upper_bound('\n\n'.join([*context_parts, block])) <= max(0, context_budget - notice_reserve):
                selected_preview = preview
                context_parts.append(block)
                break
        if selected_preview is None:
            decision['filter_reasons'].append('context_budget')
            continue
        decision['injected'] = True
        injected.append((decision, doc, selected_preview))
        if grade != 'DIRECT':
            reference_counts[grade] += 1
    direct = [d for d, _, _ in injected if d['evidence_grade'] == 'DIRECT']
    covered = {key for decision in direct for key in decision['evidence_scope']}
    missing_entities = [key for key in targets if key not in covered]
    sufficient = bool(direct) and not missing_entities
    evidence_status = 'DIRECT_AVAILABLE' if sufficient else 'EVIDENCE_INSUFFICIENT'
    notice = ("[DIRECT_AVAILABLE] 仅 DIRECT 可以支持其明确覆盖的实体与事实；RELATED/BACKGROUND 只作标注用途的参考。"
              if sufficient else insufficient_notice)
    if analysis.ambiguous_entity:
        notice += " 核心实体别名有歧义，需要精确业务 ID 或名称。"
    context_parts.insert(0, notice)
    retrieval_stats = {'matched_count': len(eligible), 'selected_count': len(injected),
                       'candidate_count': len(readable), 'direct_count': len(direct),
                       'evidence_status': evidence_status, 'missing_entities': missing_entities, 'truncated': len(eligible) > len(injected)}
    if stats is not None:
        stats.update(retrieval_stats, pending_count=len(processing), unreadable_count=len(unreadable),
                     retrieval_trace={'query': query_text, 'query_analysis': analysis.trace(),
                                      'candidate_count': len(readable), 'eligible_count': len(eligible),
                                      'ranking': [d for d, _ in ranked], 'evidence_status': evidence_status,
                                      'injected_ids': [d['document_id'] for d, _, _ in injected],
                                      'context_budget': context_budget})
    for decision, doc, preview in injected:
        if sources is not None:
            sources.append({'type': 'knowledge_base', 'name': doc.name, 'id': str(doc.knowledge_base_id),
                            'document_id': str(doc.id), 'description': f"[{decision['evidence_grade']}] {decision['purpose']}\n{preview}",
                            'doc_count': 1, 'evidence_grade': decision['evidence_grade'], 'purpose': decision['purpose'],
                            'entity_relation': decision['entity_relation'], 'evidence_scope': decision['evidence_scope'], **retrieval_stats})
    if processing:
        context_parts.append("### 文档正在识别\n" + "\n".join(processing)
                             + "\n这些文档已上传，系统正在进行文字识别。请告知用户稍后重试，无需重新上传；不得编造尚未识别的内容。")
    if unreadable:
        context_parts.append(
            "### 相关文件读取失败\n以下文件存在于可访问的知识库，但没有可读取的正文：\n"
            + "\n".join(f"- {name}" for name in unreadable)
            + "\n请告知用户需要补充可提取文字的原文件或 OCR 文本；不得据文件名或历史回复编造政策内容。"
        )
    output = "\n\n".join(context_parts)
    if token_upper_bound(output) > context_budget:
        # Optional extraction-status lists must not consume the evidence budget.
        output = "\n\n".join([notice, *context_parts[1:1 + len(injected)]])
    if token_upper_bound(output) > context_budget:
        output = "Evidence Insufficient"
        if token_upper_bound(output) > context_budget:
            output = ""  # The caller cannot even fit a status message.
        if sources is not None:
            selected_ids = {str(doc.id) for _, doc, _ in injected}
            sources[:] = [s for s in sources if s.get('document_id') not in selected_ids]
        if stats is not None:
            stats.update(budget_too_small=True, selected_count=0, direct_count=0,
                         evidence_status='EVIDENCE_INSUFFICIENT')
            stats['retrieval_trace'].update(injected_ids=[], evidence_status='EVIDENCE_INSUFFICIENT')
    if stats is not None:
        stats['retrieval_trace']['injected_context'] = output
        stats['retrieval_trace']['missing_entities'] = missing_entities
    return output
