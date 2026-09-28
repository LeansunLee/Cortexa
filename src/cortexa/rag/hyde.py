"""HyDE (Hypothetical Document Embeddings) retrieval.

Uses LLM to generate a hypothetical answer, then uses its embedding
for vector search instead of the raw query. This bridges the gap between
query phrasing and document phrasing.
"""

from __future__ import annotations
from cortexa.usage.context import usage_action

from dataclasses import dataclass
from typing import List


@dataclass
class HyDEQuery:
    """Result of HyDE query expansion."""
    original_query: str
    hypothetical_answer: str


@usage_action("retrieval_hyde", source="knowledge")
def generate_hypothetical_answer(
    query: str,
    llm=None,
    prompt_template: str | None = None,
) -> HyDEQuery:
    """Generate a hypothetical answer for the given query using LLM.

    Args:
        query: The user's original question.
        llm: A LangChain-compatible LLM instance. If None, creates one from config.
        prompt_template: Custom prompt template. Uses default if None.

    Returns:
        HyDEQuery with the original query and generated hypothetical answer.
    """
    if prompt_template is None:
        prompt_template = (
            "请根据以下问题，写一段可能出现在相关文档中的回答片段。"
            "回答应该像文档内容一样客观、具体，包含可能的相关信息。\n"
            "问题：{query}\n"
            "文档片段："
        )

    if llm is None:
        from cortexa.config.llm_providers import create_llm
        llm = create_llm()

    prompt = prompt_template.format(query=query)
    response = llm.invoke(prompt)
    hypothetical_answer = response.content if hasattr(response, "content") else str(response)

    return HyDEQuery(
        original_query=query,
        hypothetical_answer=hypothetical_answer.strip(),
    )


def hyde_retrieve(
    query: str,
    vector_search_fn,
    llm=None,
    top_k: int = 5,
    prompt_template: str | None = None,
) -> list:
    """Perform HyDE retrieval: generate hypothetical answer, then vector search.

    Args:
        query: The user's original question.
        vector_search_fn: A callable that takes (embedding: List[float], top_k: int)
                         and returns a list of retrieval results.
        llm: LLM instance for generating hypothetical answer.
        top_k: Number of results to return.
        prompt_template: Custom prompt for hypothetical answer generation.

    Returns:
        List of retrieval results from vector search.
    """
    from cortexa.rag.embedder import embed_query

    # Step 1: Generate hypothetical answer
    hyde_result = generate_hypothetical_answer(query, llm, prompt_template)

    # Step 2: Embed the hypothetical answer
    hypothetical_embedding = embed_query(hyde_result.hypothetical_answer)

    # Step 3: Vector search with the hypothetical embedding
    results = vector_search_fn(hypothetical_embedding, top_k)

    return results
