"""BM25 search for Chinese documents - no external dependencies needed."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from typing import List, Dict, Tuple

import jieba
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.db.models import Document, DocumentChunk


@dataclass
class BM25Result:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    content: str
    score: float
    metadata: dict | None = None


class BM25:
    """Okapi BM25 scoring algorithm."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = 0
        self.avg_doc_len = 0.0
        self.doc_lens: List[int] = []
        self.tf: List[Dict[str, int]] = []
        self.df: Dict[str, int] = {}

    def fit(self, documents: List[List[str]]):
        """Build index from tokenized documents."""
        self.doc_count = len(documents)
        total_len = 0
        self.doc_lens = []
        self.tf = []
        self.df = {}

        for doc in documents:
            doc_len = len(doc)
            self.doc_lens.append(doc_len)
            total_len += doc_len

            # Term frequency for this document
            tf_doc: Dict[str, int] = {}
            for term in doc:
                tf_doc[term] = tf_doc.get(term, 0) + 1
            self.tf.append(tf_doc)

            # Document frequency
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1

        self.avg_doc_len = total_len / self.doc_count if self.doc_count > 0 else 0

    def score(self, query: List[str], doc_idx: int) -> float:
        """Calculate BM25 score for a query against a document."""
        score = 0.0
        doc_len = self.doc_lens[doc_idx]

        for term in query:
            if term not in self.tf[doc_idx]:
                continue

            tf = self.tf[doc_idx][term]
            df = self.df.get(term, 0)

            # IDF component
            idf = math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1)

            # TF component with length normalization
            tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len))

            score += idf * tf_norm

        return score

    def search(self, query: List[str], top_k: int = 10) -> List[Tuple[int, float]]:
        """Search and return top-k document indices with scores."""
        scores = []
        for i in range(self.doc_count):
            s = self.score(query, i)
            if s > 0:
                scores.append((i, s))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


def tokenize(text: str) -> List[str]:
    """Tokenize text using jieba with stopword removal."""
    # Basic Chinese stopwords
    stopwords = {
        '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
        '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
        '自己', '这', '他', '她', '它', '们', '那', '被', '从', '把', '对', '让', '给',
        '能', '可以', '这个', '那个', '什么', '怎么', '为什么', '吗', '呢', '啊', '吧',
        '而', '但', '但是', '如果', '因为', '所以', '虽然', '不过', '然后', '或者',
        '与', '及', '或', '等', '之', '其', '此', '该', '每', '各', '所有',
        '将', '已', '正', '再', '还', '比', '更', '最', '太', '非常', '十分',
        '做', '用', '来', '以', '为', '中', '里', '后', '前', '时', '年', '月', '日',
        '大', '小', '多', '少', '高', '低', '新', '旧', '好', '坏',
        '可', '可能', '应该', '需要', '能够', '可以', '进行', '使用', '通过', '根据',
        '关于', '对于', '由于', '按照', '除了', '以及', '而且', '但是', '然而',
        '因此', '所以', '于是', '接着', '首先', '其次', '最后', '总之',
    }

    # Tokenize with jieba
    words = jieba.cut(text)

    # Filter: keep words with length >= 2, not in stopwords, not pure punctuation/numbers
    tokens = []
    for w in words:
        w = w.strip()
        if len(w) < 2:
            continue
        if w.lower() in stopwords:
            continue
        # Skip pure punctuation or numbers
        if re.match(r'^[\d\W]+$', w):
            continue
        tokens.append(w.lower())

    return tokens


async def bm25_retrieve(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.1,
) -> List[BM25Result]:
    """Retrieve relevant document chunks using BM25 scoring."""
    if not knowledge_base_ids or not query_text.strip():
        return []

    # Convert string IDs to UUIDs
    kb_uuids = []
    for kid in knowledge_base_ids:
        try:
            kb_uuids.append(uuid.UUID(kid))
        except (ValueError, AttributeError):
            continue

    if not kb_uuids:
        return []

    # Load all chunks for these knowledge bases
    kb_placeholders = ", ".join([f"'{kid}'" for kid in kb_uuids])
    sql = text(f"""
        SELECT
            dc.id as chunk_id,
            dc.document_id,
            d.name as document_name,
            d.content as summary,
            dc.content,
            dc.knowledge_base_id
        FROM t_document_chunks dc
        JOIN t_documents d ON d.id = dc.document_id
        JOIN t_knowledge_bases kb ON kb.id = dc.knowledge_base_id
        WHERE dc.knowledge_base_id IN ({kb_placeholders})
          AND kb.status = 'active'
          AND d.status = 'active'
          AND (d.valid_until IS NULL OR d.valid_until >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date)
          AND dc.content IS NOT NULL
          AND length(dc.content) > 0
    """)

    result = await db.execute(sql)
    rows = result.fetchall()

    if not rows:
        return []

    from types import SimpleNamespace
    from cortexa.rag.document_selection import rank_documents
    documents, full_texts = {}, {}
    for row in rows:
        key = str(row.document_id)
        documents[key] = SimpleNamespace(id=row.document_id, name=row.document_name,
                                         content=getattr(row, 'summary', '') or '')
        full_texts.setdefault(key, []).append(row.content)
    ranked = rank_documents(list(documents.values()), query_text,
                            {key: '\n'.join(parts) for key, parts in full_texts.items()})
    candidate_ids = {str(doc.id) for _, doc in ranked}
    rows = [row for row in rows if str(row.document_id) in candidate_ids]
    if not rows:
        return []

    # Tokenize all chunks
    doc_tokens = []
    for row in rows:
        tokens = tokenize(row.content)
        doc_tokens.append(tokens)

    # Tokenize query
    query_tokens = tokenize(query_text)

    if not query_tokens:
        return []

    # Build BM25 index and search
    bm25 = BM25()
    bm25.fit(doc_tokens)
    results = bm25.search(query_tokens, top_k=len(rows))

    # Filter and format results
    bm25_results = []
    seen_contents = set()  # Deduplicate

    for idx, score in results:
        if score < min_score:
            continue

        row = rows[idx]
        content = row.content

        # Skip duplicate content
        content_hash = (row.document_id, content)
        if content_hash in seen_contents:
            continue
        seen_contents.add(content_hash)

        bm25_results.append(BM25Result(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            document_name=row.document_name,
            content=content[:2000],  # Limit content length
            score=score,
        ))

    selected = bm25_results[:top_k]
    for item in selected:
        item.metadata = {'matched_count': len(bm25_results), 'selected_count': len(selected),
                         'truncated': len(bm25_results) > len(selected),
                         'matched_document_count': len(candidate_ids)}
    return selected
