"""Shared candidate recall followed by deterministic entity/evidence gating."""

from cortexa.rag.relevance import select_documents


def rank_documents(documents, query, full_texts, *, score_fn=None, algorithm="lexical"):
    _, ranked = select_documents(documents, query, full_texts, score_fn=score_fn, algorithm=algorithm)
    return [(decision["raw_score"], doc) for decision, doc in ranked if decision["eligible"]]
