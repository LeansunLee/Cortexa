from __future__ import annotations

import math
from collections import Counter
from typing import Any


def _tokenize(text: str) -> list[str]:
    return [token for token in text.lower().split() if token]


def _split_chunks(text: str, max_tokens: int = 220, overlap: int = 40) -> list[str]:
    tokens = _tokenize(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + max_tokens)
        chunk = " ".join(tokens[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end == len(tokens):
            break
        start = end - overlap
    return chunks


class InMemoryStore:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.df: Counter[str] = Counter()
        self.total_docs: int = 0

    def add_texts(self, texts: list[str], meta: Any = None) -> None:
        for text in texts:
            tokens = _tokenize(text)
            unique_tokens = set(tokens)
            self.documents.append({"text": text, "meta": meta, "tokens": tokens})
            for token in unique_tokens:
                self.df[token] += 1
            self.total_docs += 1

    def query(self, query_text: str, top_k: int = 3) -> list[dict[str, Any]]:
        q_tokens = _tokenize(query_text)
        q_counts = Counter(q_tokens)

        scores: list[tuple[int, float]] = []
        for idx, doc in enumerate(self.documents):
            doc_counts = Counter(doc["tokens"])
            score = 0.0
            for token, tf in q_counts.items():
                df = self.df.get(token, 0)
                idf = math.log((1 + self.total_docs) / (1 + df)) if df else 0.0
                score += tf * doc_counts.get(token, 0) * idf
            scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        results: list[dict[str, Any]] = []
        for idx, score in scores[:top_k]:
            doc = self.documents[idx]
            results.append({"text": doc["text"], "score": score, "meta": doc["meta"]})
        return results


_STORES: dict[str, InMemoryStore] = {}


def _get_store(collection: str) -> InMemoryStore:
    if collection not in _STORES:
        _STORES[collection] = InMemoryStore()
    return _STORES[collection]


def ingest_texts(texts: list[str], collection: str = "default", chunk: bool = True) -> int:
    store = _get_store(collection)
    prepared: list[str] = []
    for text in texts:
        prepared.extend(_split_chunks(text) if chunk else [text])
    store.add_texts(prepared, meta={"collection": collection})
    return len(prepared)


def retrieve(query: str, collection: str = "default", top_k: int = 3) -> list[dict[str, Any]]:
    store = _get_store(collection)
    if not store.documents:
        ingest_texts(
            [
                "LangGraph is a library for building stateful, multi-actor applications with LLMs.",
                "LangGraph supports tool use, human-in-the-loop, persistence, and streaming.",
                "Use LangGraph when you need cyclic or human-supervised agent workflows.",
                "LangChain provides building blocks; LangGraph adds orchestration over agents.",
                "Multi-agent systems are useful when tasks benefit from specialization and handoffs.",
            ],
            collection=collection,
            chunk=False,
        )
    return store.query(query, top_k=top_k)
