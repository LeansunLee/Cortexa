"""Parent-Child Document Retriever.

Uses small child chunks for precise retrieval, then returns the larger
parent chunk as context for the LLM. This balances retrieval precision
with generation context quality.

NOTE: Requires DB schema changes (see migrations/add_parent_child_fields.sql):
  - DocumentChunk needs: parent_chunk_id (UUID), is_parent (bool)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List

from agentdevstu.rag.chunker import Chunk


@dataclass
class ParentChildConfig:
    """Configuration for parent-child chunking."""
    parent_chunk_size: int = 2000
    parent_chunk_overlap: int = 200
    child_chunk_size: int = 500
    child_chunk_overlap: int = 50
    separators: List[str] | None = None


def split_parent_child(
    text: str,
    config: ParentChildConfig | None = None,
) -> tuple[List[Chunk], dict[str, List[Chunk]]]:
    """Split document into parent chunks and their child chunks.

    Args:
        text: The full document text.
        config: Parent-child configuration.

    Returns:
        Tuple of (parent_chunks, mapping of parent_uuid_str -> child_chunks).
    """
    if config is None:
        config = ParentChildConfig()

    separators = config.separators or ["\n\n", "\n", "。", ".", " "]

    # Step 1: Split into parent chunks
    parent_chunks = _split_chunks(
        text,
        chunk_size=config.parent_chunk_size,
        chunk_overlap=config.parent_chunk_overlap,
        separators=separators,
    )

    # Assign UUIDs to parents
    for parent in parent_chunks:
        if parent.metadata is None:
            parent.metadata = {}
        parent.metadata["id"] = str(uuid.uuid4())

    # Step 2: For each parent chunk, split into child chunks
    parent_child_map: dict[str, List[Chunk]] = {}

    for parent in parent_chunks:
        parent_id = parent.metadata["id"]
        child_chunks = _split_chunks(
            parent.content,
            chunk_size=config.child_chunk_size,
            chunk_overlap=config.child_chunk_overlap,
            separators=separators,
        )

        # Tag children with parent reference
        for child in child_chunks:
            if child.metadata is None:
                child.metadata = {}
            child.metadata["parent_id"] = parent_id

        parent_child_map[parent_id] = child_chunks

    return parent_chunks, parent_child_map


def _split_chunks(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 128,
    separators: List[str] | None = None,
) -> List[Chunk]:
    """Split text into chunks using recursive character splitting."""
    from agentdevstu.rag.chunker import chunk_text
    return chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=separators)


async def index_parent_child(
    db_session,
    document_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    text: str,
    config: ParentChildConfig | None = None,
) -> int:
    """Index a document using parent-child chunking.

    Creates parent chunks and child chunks in the DB, with child chunks
    referencing their parent for retrieval.

    Args:
        db_session: Async DB session.
        document_id: The document UUID.
        knowledge_base_id: The knowledge base UUID.
        text: The full document text.
        config: Parent-child chunking configuration.

    Returns:
        Number of child chunks created.
    """
    from agentdevstu.db.models import DocumentChunk

    if config is None:
        config = ParentChildConfig()

    # Split into parents and children
    parent_chunks, parent_child_map = split_parent_child(text, config)

    # Delete existing chunks for this document
    from sqlalchemy import delete
    await db_session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )

    child_count = 0

    # Store parent chunks and map temp IDs to DB UUIDs
    parent_id_map: dict[str, uuid.UUID] = {}  # temp_id -> db_uuid
    for parent in parent_chunks:
        db_parent_id = uuid.uuid4()
        parent_id_map[parent.metadata["id"]] = db_parent_id

        parent_record = DocumentChunk(
            id=db_parent_id,
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            chunk_index=parent.index,
            content=parent.content,
            token_count=parent.token_count,
            metadata_json={"is_parent": True, "parent_chunk_size": config.parent_chunk_size},
        )
        db_session.add(parent_record)

    # Store child chunks with parent reference
    for parent_id_str, children in parent_child_map.items():
        parent_db_id = parent_id_map.get(parent_id_str)
        if not parent_db_id:
            continue

        for child in children:
            child_record = DocumentChunk(
                document_id=document_id,
                knowledge_base_id=knowledge_base_id,
                chunk_index=child.index,
                content=child.content,
                token_count=child.token_count,
                metadata_json={
                    "is_parent": False,
                    "parent_chunk_id": str(parent_db_id),
                    "parent_chunk_size": config.parent_chunk_size,
                },
            )
            db_session.add(child_record)
            child_count += 1

    await db_session.flush()
    return child_count


async def parent_child_retrieve(
    db_session,
    knowledge_base_ids: List[str],
    query_text: str,
    top_k: int = 5,
    search_fn=None,
) -> List[dict]:
    """Retrieve using parent-child strategy.

    1. Search child chunks for precise matching
    2. Return parent chunks as context

    Args:
        db_session: Async DB session.
        knowledge_base_ids: List of knowledge base IDs to search.
        query_text: The search query.
        top_k: Number of results to return.
        search_fn: Optional custom search function. If None, uses BM25.

    Returns:
        List of results with parent context.
    """
    import uuid as uuid_lib
    from sqlalchemy import text
    from agentdevstu.db.models import DocumentChunk, Document

    if not knowledge_base_ids or not query_text.strip():
        return []

    kb_uuids = []
    for kid in knowledge_base_ids:
        try:
            kb_uuids.append(uuid_lib.UUID(kid))
        except (ValueError, AttributeError):
            continue

    if not kb_uuids:
        return []

    # Step 1: Search child chunks
    if search_fn:
        child_results = await search_fn(db_session, knowledge_base_ids, query_text, top_k * 2)
    else:
        from agentdevstu.rag.bm25_search import bm25_retrieve
        child_results = await bm25_retrieve(db_session, knowledge_base_ids, query_text, top_k * 2)

    # Step 2: Collect parent chunk IDs from child metadata
    parent_ids = set()
    child_to_parent = {}
    for result in child_results:
        metadata = getattr(result, 'metadata', None) or {}
        parent_id_str = metadata.get("parent_chunk_id")
        if parent_id_str:
            try:
                parent_id = uuid_lib.UUID(parent_id_str)
                parent_ids.add(parent_id)
                child_to_parent[result.chunk_id] = parent_id
            except (ValueError, AttributeError):
                pass

    # Step 3: Fetch parent chunks
    parent_chunks = {}
    if parent_ids:
        parent_id_list = ", ".join([f"'{pid}'" for pid in parent_ids])
        sql = text(f"""
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                d.name as document_name,
                dc.content
            FROM t_document_chunks dc
            JOIN t_documents d ON d.id = dc.document_id
            JOIN t_knowledge_bases kb ON kb.id = dc.knowledge_base_id
            WHERE dc.id IN ({parent_id_list})
              AND kb.status = 'active'
              AND d.status = 'active'
              AND (d.valid_until IS NULL OR d.valid_until >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date)
        """)
        result = await db_session.execute(sql)
        for row in result.fetchall():
            parent_chunks[row.chunk_id] = {
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "document_name": row.document_name,
                "content": row.content,
            }

    # Step 4: Build results - child match + parent context
    final_results = []
    seen_parents = set()

    for child_result in child_results[:top_k * 2]:
        parent_id = child_to_parent.get(child_result.chunk_id)
        parent_data = parent_chunks.get(parent_id) if parent_id else None

        parent_key = parent_id or child_result.chunk_id
        if parent_key in seen_parents:
            continue
        seen_parents.add(parent_key)

        final_results.append({
            "chunk_id": child_result.chunk_id,
            "document_id": child_result.document_id,
            "document_name": child_result.document_name,
            "child_content": child_result.content,
            "parent_content": parent_data["content"] if parent_data else child_result.content,
            "score": child_result.score,
            "is_parent_context": parent_data is not None,
        })

        if len(final_results) >= top_k:
            break

    return final_results
