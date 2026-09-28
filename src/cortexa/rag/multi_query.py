"""Multi-Query retrieval with Reciprocal Rank Fusion (RRF).

Generates multiple query variants using LLM, retrieves results for each,
and merges them using RRF to improve recall.
"""

from __future__ import annotations
from cortexa.usage.context import usage_action

import math
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Any


@dataclass
class MultiQueryConfig:
    """Configuration for multi-query retrieval."""
    num_variants: int = 3
    top_k_per_variant: int = 5
    rrf_k: int = 60  # RRF constant (higher = less weight to top ranks)
    prompt_template: str = (
        "你是一个AI语言模型助手。你的任务是基于给定的原始问题，"
        "生成{num_variants}个不同角度的变体问题，帮助从文档中检索相关信息。\n"
        "要求：\n"
        "1. 每个变体从不同角度提问\n"
        "2. 使用换行符分隔每个变体\n"
        "3. 不要包含数字序号\n"
        "4. 仅返回变体问题，不要添加任何描述\n\n"
        "原始问题：{query}"
    )


@usage_action("retrieval_rewrite", source="knowledge")
def generate_query_variants(
    query: str,
    llm=None,
    config: MultiQueryConfig | None = None,
) -> List[str]:
    """Generate query variants using LLM.

    Args:
        query: The original user query.
        llm: LLM instance. If None, creates one from config.
        config: MultiQuery configuration.

    Returns:
        List of query variants including the original query.
    """
    if config is None:
        config = MultiQueryConfig()

    if llm is None:
        from cortexa.config.llm_providers import create_llm
        llm = create_llm()

    prompt = config.prompt_template.format(
        num_variants=config.num_variants,
        query=query,
    )

    response = llm.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)

    # Parse variants from response
    variants = [
        line.strip()
        for line in content.strip().split("\n")
        if line.strip() and not line.strip().startswith(("#", "-", "*", "1.", "2.", "3."))
    ]

    # Ensure we have variants, fallback to original query
    if not variants:
        variants = [query]

    # Always include original query
    if query not in variants:
        variants.insert(0, query)

    return variants[:config.num_variants + 1]


def reciprocal_rank_fusion(
    result_lists: List[List[Dict[str, Any]]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Args:
        result_lists: List of ranked result lists. Each result must have 'id' and 'score'.
        k: RRF constant. Higher k means less influence from top ranks.

    Returns:
        Merged and re-ranked results, deduplicated by 'id'.
    """
    # Collect all scores per document
    doc_scores: Dict[str, float] = {}
    doc_data: Dict[str, Dict[str, Any]] = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list, start=1):
            doc_id = result.get("id") or result.get("chunk_id")
            if doc_id is None:
                continue
            doc_id_str = str(doc_id)

            # RRF score: 1 / (k + rank)
            rrf_score = 1.0 / (k + rank)

            if doc_id_str in doc_scores:
                doc_scores[doc_id_str] += rrf_score
            else:
                doc_scores[doc_id_str] = rrf_score
                doc_data[doc_id_str] = result

    # Sort by fused score
    sorted_ids = sorted(doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True)

    merged = []
    for doc_id_str in sorted_ids:
        entry = dict(doc_data[doc_id_str])
        entry["rrf_score"] = doc_scores[doc_id_str]
        merged.append(entry)

    return merged


def multi_query_retrieve(
    query: str,
    search_fn: Callable[[str, int], List[Dict[str, Any]]],
    llm=None,
    config: MultiQueryConfig | None = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Perform multi-query retrieval with RRF fusion.

    Args:
        query: The original user query.
        search_fn: A callable that takes (query_text, top_k) and returns
                   a list of dicts with 'id'/'chunk_id' and 'score' keys.
        llm: LLM instance for generating query variants.
        config: MultiQuery configuration.
        top_k: Final number of results to return.

    Returns:
        Merged and ranked results.
    """
    if config is None:
        config = MultiQueryConfig()

    # Generate query variants
    variants = generate_query_variants(query, llm, config)

    # Retrieve for each variant
    result_lists = []
    for variant in variants:
        try:
            results = search_fn(variant, config.top_k_per_variant)
            result_lists.append(results)
        except Exception as e:
            print(f"[MultiQuery] Retrieval failed for variant '{variant}': {e}")
            continue

    if not result_lists:
        return []

    # Merge with RRF
    merged = reciprocal_rank_fusion(result_lists, k=config.rrf_k)

    return merged[:top_k]
