"""RAG retrieval service - unified retrieval with multiple strategies.

Supports:
- BM25 keyword retrieval (default)
- HyDE (Hypothetical Document Embeddings)
- Multi-Query with RRF fusion
- Contextual Retrieval
- Parent-Child retrieval
"""

from __future__ import annotations

import uuid
import os
from dataclasses import dataclass, field
from typing import List, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.db.models import DocumentChunk, Document


@dataclass
class RetrievalResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    content: str
    score: float
    metadata: dict | None = None


@dataclass
class RetrievalConfig:
    """Unified configuration for all retrieval strategies."""
    strategy: Literal["bm25", "hyde", "multi_query", "ensemble", "parent_child"] = "bm25"
    top_k: int = 5
    min_score: float = 0.1
    # HyDE specific
    hyde_prompt_template: str | None = None
    # Multi-Query specific
    num_query_variants: int = 3
    rrf_k: int = 60
    # Ensemble specific
    bm25_weight: float = 0.5
    vector_weight: float = 0.5
    # Parent-Child specific
    use_parent_context: bool = True


async def retrieve_relevant_chunks(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.1,
    strategy: str = "bm25",
    config: RetrievalConfig | None = None,
) -> List[RetrievalResult]:
    """Retrieve the most relevant document chunks for a query.

    Args:
        db: Async database session.
        knowledge_base_ids: List of knowledge base IDs to search.
        query_text: The search query.
        top_k: Number of results to return.
        min_score: Minimum score threshold.
        strategy: Retrieval strategy name.
        config: Optional retrieval configuration.

    Returns:
        List of RetrievalResult objects.
    """
    if not knowledge_base_ids or not query_text.strip():
        return []

    top_k = max(1, min(int(top_k), int(os.getenv("KNOWLEDGE_SEARCH_MAX_TOP_K", "50"))))

    if config is None:
        config = RetrievalConfig(strategy=strategy, top_k=top_k, min_score=min_score)
    else:
        config.strategy = strategy
        config.top_k = top_k
        config.min_score = min_score

    try:
        if config.strategy == "hyde":
            results = await _retrieve_hyde(db, knowledge_base_ids, query_text, config)
        elif config.strategy == "multi_query":
            results = await _retrieve_multi_query(db, knowledge_base_ids, query_text, config)
        elif config.strategy == "ensemble":
            results = await _retrieve_ensemble(db, knowledge_base_ids, query_text, config)
        elif config.strategy == "parent_child":
            results = await _retrieve_parent_child(db, knowledge_base_ids, query_text, config)
        else:
            # Default: BM25
            results = await _retrieve_bm25(db, knowledge_base_ids, query_text, config)

        return [
            RetrievalResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_name=r.document_name,
                content=r.content,
                score=r.score,
                metadata=r.metadata,
            )
            for r in results
        ]
    except Exception as e:
        print(f"[RAG] Retrieval failed (strategy={config.strategy}): {e}")
        return []


async def _retrieve_bm25(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    config: RetrievalConfig,
) -> List[RetrievalResult]:
    """BM25-only retrieval."""
    from agentdevstu.rag.bm25_search import bm25_retrieve
    results = await bm25_retrieve(db, knowledge_base_ids, query_text, config.top_k, config.min_score)
    return [
        RetrievalResult(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            document_name=r.document_name,
            content=r.content,
            score=r.score,
            metadata=r.metadata,
        )
        for r in results
    ]


async def _retrieve_hyde(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    config: RetrievalConfig,
) -> List[RetrievalResult]:
    """HyDE retrieval: generate hypothetical answer, then search."""
    from agentdevstu.rag.hyde import generate_hypothetical_answer
    from agentdevstu.rag.embedder import embed_query

    # Generate hypothetical answer
    hyde_result = generate_hypothetical_answer(query_text, prompt_template=config.hyde_prompt_template)
    print(f"[HyDE] Original query: {query_text}")
    print(f"[HyDE] Hypothetical answer: {hyde_result.hypothetical_answer[:100]}...")

    # Try vector search first, fallback to BM25 on hypothetical answer
    try:
        embedding = embed_query(hyde_result.hypothetical_answer)
        results = await _vector_search(db, knowledge_base_ids, embedding, config)
        if results:
            return results
    except Exception as e:
        print(f"[HyDE] Vector search failed, falling back to BM25: {e}")

    # Fallback: BM25 on hypothetical answer
    from agentdevstu.rag.bm25_search import bm25_retrieve
    results = await bm25_retrieve(db, knowledge_base_ids, hyde_result.hypothetical_answer, config.top_k, config.min_score)
    return [
        RetrievalResult(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            document_name=r.document_name,
            content=r.content,
            score=r.score,
            metadata={"hyde_hypothetical": hyde_result.hypothetical_answer[:200]},
        )
        for r in results
    ]


async def _retrieve_multi_query(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    config: RetrievalConfig,
) -> List[RetrievalResult]:
    """Multi-Query retrieval with RRF fusion."""
    from agentdevstu.rag.multi_query import generate_query_variants, reciprocal_rank_fusion, MultiQueryConfig
    from agentdevstu.rag.bm25_search import bm25_retrieve

    mq_config = MultiQueryConfig(
        num_variants=config.num_query_variants,
        rrf_k=config.rrf_k,
    )

    # Generate query variants
    variants = generate_query_variants(query_text, config=mq_config)
    print(f"[MultiQuery] Generated {len(variants)} variants: {variants}")

    # Retrieve for each variant
    result_lists = []
    for variant in variants:
        try:
            bm25_results = await bm25_retrieve(db, knowledge_base_ids, variant, config.top_k * 2, config.min_score)
            result_dicts = [
                {"id": str(r.chunk_id), "chunk_id": r.chunk_id, "document_id": r.document_id,
                 "document_name": r.document_name, "content": r.content, "score": r.score}
                for r in bm25_results
            ]
            result_lists.append(result_dicts)
        except Exception as e:
            print(f"[MultiQuery] Retrieval failed for variant '{variant}': {e}")
            continue

    if not result_lists:
        return []

    # Merge with RRF
    merged = reciprocal_rank_fusion(result_lists, k=config.rrf_k)

    # Deduplicate and limit
    seen = set()
    final = []
    for item in merged:
        chunk_id = item.get("chunk_id")
        if chunk_id and chunk_id not in seen:
            seen.add(chunk_id)
            final.append(RetrievalResult(
                chunk_id=item["chunk_id"],
                document_id=item["document_id"],
                document_name=item["document_name"],
                content=item["content"][:2000],
                score=item.get("rrf_score", item.get("score", 0)),
                metadata={"variants_used": variants},
            ))
        if len(final) >= config.top_k:
            break

    return final


async def _retrieve_ensemble(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    config: RetrievalConfig,
) -> List[RetrievalResult]:
    """Ensemble retrieval: BM25 + Vector with RRF fusion."""
    # BM25 results
    from agentdevstu.rag.bm25_search import bm25_retrieve
    bm25_results = await bm25_retrieve(db, knowledge_base_ids, query_text, config.top_k * 2, config.min_score)

    bm25_dicts = [
        {"id": str(r.chunk_id), "chunk_id": r.chunk_id, "document_id": r.document_id,
         "document_name": r.document_name, "content": r.content, "score": r.score}
        for r in bm25_results
    ]

    # Vector results
    vector_dicts = []
    try:
        from agentdevstu.rag.embedder import embed_query
        embedding = embed_query(query_text)
        vector_results = await _vector_search(db, knowledge_base_ids, embedding, config)
        vector_dicts = [
            {"id": str(r.chunk_id), "chunk_id": r.chunk_id, "document_id": r.document_id,
             "document_name": r.document_name, "content": r.content, "score": r.score}
            for r in vector_results
        ]
    except Exception as e:
        print(f"[Ensemble] Vector search failed: {e}")

    if not bm25_dicts and not vector_dicts:
        return []

    # Merge with weighted RRF
    from agentdevstu.rag.multi_query import reciprocal_rank_fusion

    # Apply weights by duplicating results
    weighted_lists = []
    if bm25_dicts:
        weighted_lists.append(bm25_dicts)
    if vector_dicts:
        weighted_lists.append(vector_dicts)

    merged = reciprocal_rank_fusion(weighted_lists, k=config.rrf_k)

    # Deduplicate
    seen = set()
    final = []
    for item in merged:
        chunk_id = item.get("chunk_id")
        if chunk_id and chunk_id in seen:
            continue
        seen.add(chunk_id)
        final.append(RetrievalResult(
            chunk_id=item["chunk_id"],
            document_id=item["document_id"],
            document_name=item["document_name"],
            content=item["content"][:2000],
            score=item.get("rrf_score", 0),
            metadata={"strategy": "ensemble"},
        ))
        if len(final) >= config.top_k:
            break

    return final


async def _retrieve_parent_child(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    config: RetrievalConfig,
) -> List[RetrievalResult]:
    """Parent-Child retrieval: search children, return parents."""
    from agentdevstu.rag.parent_child import parent_child_retrieve

    results = await parent_child_retrieve(
        db, knowledge_base_ids, query_text, config.top_k
    )

    return [
        RetrievalResult(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            document_name=r["document_name"],
            content=r["parent_content"] if config.use_parent_context else r["child_content"],
            score=r["score"],
            metadata={
                "child_content": r["child_content"],
                "is_parent_context": r["is_parent_context"],
            },
        )
        for r in results
    ]


async def _vector_search(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_embedding: List[float],
    config: RetrievalConfig,
) -> List[RetrievalResult]:
    """Vector cosine similarity search using stored embeddings."""
    import struct
    from sqlalchemy import text
    from agentdevstu.rag.embedder import embedding_to_bytes

    kb_uuids = []
    for kid in knowledge_base_ids:
        try:
            kb_uuids.append(uuid.UUID(kid))
        except (ValueError, AttributeError):
            continue

    if not kb_uuids:
        return []

    # Use pgvector cosine distance if available, otherwise fetch and compute
    kb_placeholders = ", ".join([f"'{kid}'" for kid in kb_uuids])
    query_bytes = embedding_to_bytes(query_embedding)

    sql = text(f"""
        SELECT
            dc.id as chunk_id,
            dc.document_id,
            d.name as document_name,
            dc.content,
            dc.embedding,
            1 - (dc.embedding <=> :query_embedding::bytea) as cosine_similarity
        FROM t_document_chunks dc
        JOIN t_documents d ON d.id = dc.document_id
        JOIN t_knowledge_bases kb ON kb.id = dc.knowledge_base_id
        WHERE dc.knowledge_base_id IN ({kb_placeholders})
          AND kb.status = 'active'
          AND d.status = 'active'
          AND (d.valid_until IS NULL OR d.valid_until >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date)
          AND dc.embedding IS NOT NULL
          AND length(dc.content) > 10
        ORDER BY dc.embedding <=> :query_embedding::bytea
        LIMIT :limit
    """)

    try:
        # A failed pgvector query must not poison the caller's transaction.
        async with db.begin_nested():
            result = await db.execute(sql, {"query_embedding": query_bytes, "limit": config.top_k * 2})
            rows = result.fetchall()
    except Exception as e:
        # Fallback: fetch all and compute cosine similarity in Python
        print(f"[VectorSearch] PG cosine search failed, using Python fallback: {e}")
        rows = await _vector_search_fallback(db, kb_uuids, query_embedding, config)

    results = []
    for row in rows:
        score = float(row.cosine_similarity) if hasattr(row, 'cosine_similarity') and row.cosine_similarity else 0
        if score >= config.min_score:
            results.append(RetrievalResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_name=row.document_name,
                content=row.content[:2000],
                score=score,
            ))

    return results[:config.top_k]


async def _vector_search_fallback(
    db: AsyncSession,
    kb_uuids: list,
    query_embedding: List[float],
    config: RetrievalConfig,
):
    """Fallback vector search: fetch embeddings and compute cosine in Python."""
    import struct
    import math
    from sqlalchemy import text

    kb_placeholders = ", ".join([f"'{kid}'" for kid in kb_uuids])
    sql = text(f"""
        SELECT
            dc.id as chunk_id,
            dc.document_id,
            d.name as document_name,
            dc.content,
            dc.embedding
        FROM t_document_chunks dc
        JOIN t_documents d ON d.id = dc.document_id
        JOIN t_knowledge_bases kb ON kb.id = dc.knowledge_base_id
        WHERE dc.knowledge_base_id IN ({kb_placeholders})
          AND kb.status = 'active'
          AND d.status = 'active'
          AND (d.valid_until IS NULL OR d.valid_until >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date)
          AND dc.embedding IS NOT NULL
          AND length(dc.content) > 10
    """)

    result = await db.execute(sql)
    rows = result.fetchall()

    # Compute cosine similarity in Python
    scored_rows = []
    for row in rows:
        if row.embedding:
            # Unpack embedding bytes to floats
            num_floats = len(row.embedding) // 4
            doc_embedding = list(struct.unpack(f'{num_floats}f', row.embedding))

            # Compute cosine similarity
            dot_product = sum(a * b for a, b in zip(query_embedding, doc_embedding))
            norm_a = math.sqrt(sum(a * a for a in query_embedding))
            norm_b = math.sqrt(sum(b * b for b in doc_embedding))
            similarity = dot_product / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0

            scored_rows.append((row, similarity))

    # Sort by similarity
    scored_rows.sort(key=lambda x: x[1], reverse=True)

    # Wrap as mock rows with cosine_similarity attribute
    class MockRow:
        pass

    mock_rows = []
    for row, sim in scored_rows[:config.top_k * 2]:
        mock = MockRow()
        mock.chunk_id = row.chunk_id
        mock.document_id = row.document_id
        mock.document_name = row.document_name
        mock.content = row.content
        mock.cosine_similarity = sim
        mock_rows.append(mock)

    return mock_rows


async def index_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
) -> int:
    """Index a document: chunk it, embed it, and store in DB.

    Returns the number of chunks created.
    """
    from agentdevstu.db.models import DocumentChunk
    from agentdevstu.rag.chunker import chunk_text

    # Load document
    doc = await db.get(Document, document_id)
    if not doc:
        return 0
    from agentdevstu.data.doc_storage import load_document_content
    from starlette.concurrency import run_in_threadpool
    content = await run_in_threadpool(load_document_content, str(doc.id))
    content = content if content is not None else doc.content or ''
    if not content.strip() or (doc.metadata_json or {}).get('encoding') == 'base64' or content.startswith('JVBER'):
        return 0

    # Index the full document, not only the database summary.
    chunks = chunk_text(content)
    if not chunks:
        return 0

    # Delete existing chunks for this document
    from sqlalchemy import delete
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )

    # Generate embeddings
    chunk_texts = [c.content for c in chunks]
    embeddings = []
    try:
        from agentdevstu.rag.embedder import embed_texts
        embeddings = await run_in_threadpool(embed_texts, chunk_texts)
    except Exception as e:
        print(f"[RAG] Embedding generation failed: {e}")

    # Store chunks with embeddings
    for i, chunk in enumerate(chunks):
        embedding_bytes = None
        if i < len(embeddings) and embeddings[i]:
            try:
                from agentdevstu.rag.embedder import embedding_to_bytes
                embedding_bytes = embedding_to_bytes(embeddings[i])
            except Exception as e:
                print(f"[RAG] Embedding serialization failed for chunk {i}: {e}")

        chunk_record = DocumentChunk(
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            chunk_index=chunk.index,
            content=chunk.content,
            token_count=chunk.token_count,
            embedding=embedding_bytes,
            metadata_json=chunk.metadata,
        )
        db.add(chunk_record)

    await db.flush()
    return len(chunks)


# --- Public KB Priority Rules ---


async def classify_knowledge_bases(
    db: AsyncSession,
    kb_ids: List[str],
) -> tuple[List[str], List[str]]:
    """Classify knowledge base IDs into public (workspace-level) and agent-specific.

    Public KBs have agent_id = NULL in the knowledge_bases table.
    Agent-specific KBs have agent_id != NULL.

    Args:
        db: Async database session.
        kb_ids: List of knowledge base ID strings.

    Returns:
        Tuple of (public_kb_ids, agent_specific_kb_ids).
    """
    import uuid as uuid_lib
    from sqlalchemy import text

    if not kb_ids:
        return [], []

    # Filter valid UUIDs
    valid_ids = []
    for kid in kb_ids:
        try:
            valid_ids.append(str(uuid_lib.UUID(kid)))
        except (ValueError, AttributeError):
            continue

    if not valid_ids:
        return [], []

    id_placeholders = ", ".join([f"'{kid}'" for kid in valid_ids])
    sql = text(f"""
        SELECT id::text, agent_id
        FROM t_knowledge_bases
        WHERE id IN ({id_placeholders})
          AND status = 'active'
    """)

    result = await db.execute(sql)
    rows = result.fetchall()

    public_ids = []
    agent_ids = []

    for row in rows:
        kb_id_str = row[0]
        agent_id = row[1]
        if agent_id is None:
            public_ids.append(kb_id_str)
        else:
            agent_ids.append(kb_id_str)

    return public_ids, agent_ids


async def retrieve_with_priority(
    db: AsyncSession,
    knowledge_base_ids: List[str],
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.1,
    strategy: str = "bm25",
    config: RetrievalConfig | None = None,
    public_boost: float = 0.15,
) -> List[RetrievalResult]:
    """Retrieve with public KB priority rule.

    Rule: When a workspace public KB and agent-specific KB have conflicting
    content, the public KB results take priority.

    Implementation:
    1. Classify KBs into public and agent-specific groups
    2. Retrieve from both groups
    3. Boost public KB scores by public_boost
    4. Merge and re-rank by score

    Args:
        db: Async database session.
        knowledge_base_ids: List of knowledge base IDs.
        query_text: The search query.
        top_k: Number of results to return.
        min_score: Minimum score threshold.
        strategy: Retrieval strategy.
        config: Retrieval configuration.
        public_boost: Score boost for public KB results (default 0.15).

    Returns:
        Merged and ranked results with public KB priority.
    """
    if not knowledge_base_ids or not query_text.strip():
        return []

    # Classify KBs
    public_ids, agent_ids = await classify_knowledge_bases(db, knowledge_base_ids)

    if not public_ids and not agent_ids:
        return []

    # If only one type, just retrieve normally
    if not agent_ids:
        return await retrieve_relevant_chunks(
            db, public_ids, query_text, top_k, min_score, strategy, config
        )
    if not public_ids:
        return await retrieve_relevant_chunks(
            db, agent_ids, query_text, top_k, min_score, strategy, config
        )

    # Retrieve from both groups
    all_results: List[RetrievalResult] = []

    # Public KB results (with boost)
    if public_ids:
        public_results = await retrieve_relevant_chunks(
            db, public_ids, query_text, top_k * 2, min_score, strategy, config
        )
        for r in public_results:
            r.score = r.score + public_boost
            if r.metadata is None:
                r.metadata = {}
            r.metadata["kb_type"] = "public"
            r.metadata["original_score"] = r.score - public_boost
        all_results.extend(public_results)

    # Agent-specific KB results (no boost)
    if agent_ids:
        agent_results = await retrieve_relevant_chunks(
            db, agent_ids, query_text, top_k * 2, min_score, strategy, config
        )
        for r in agent_results:
            if r.metadata is None:
                r.metadata = {}
            r.metadata["kb_type"] = "agent"
            r.metadata["original_score"] = r.score
        all_results.extend(agent_results)

    # Deduplicate by content similarity (same content from different KBs)
    seen_contents: dict[str, RetrievalResult] = {}
    for r in all_results:
        # Use first 200 chars as content key for dedup
        content_key = r.content[:200].strip()
        if content_key in seen_contents:
            existing = seen_contents[content_key]
            # Keep the one with higher score (public KB wins on tie)
            if r.score > existing.score:
                seen_contents[content_key] = r
        else:
            seen_contents[content_key] = r

    # Sort by score (public KB results will rank higher due to boost)
    merged = sorted(seen_contents.values(), key=lambda x: x.score, reverse=True)

    return merged[:top_k]
