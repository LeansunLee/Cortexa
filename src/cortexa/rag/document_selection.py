"""Shared summary-first ranking with full-text recall supplementation."""


def rank_documents(documents, query, full_texts):
    from cortexa.agents.knowledge import _build_query_context, _score_text

    context = _build_query_context(query)
    scores = {}
    for doc in documents:
        score = _score_text(doc.name, doc.content or '', context)
        if score > 0:
            scores[str(doc.id)] = (score, doc)
    for doc in documents:
        score = _score_text(doc.name, full_texts.get(str(doc.id), ''), context)
        if score > 0:
            previous = scores.get(str(doc.id))
            scores[str(doc.id)] = (max(previous[0] if previous else 0, score), doc)
    return sorted(scores.values(), key=lambda item: (-item[0], str(item[1].id)))
