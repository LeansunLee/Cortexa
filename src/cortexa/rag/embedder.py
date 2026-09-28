"""Embedding service for RAG - uses LangChain's built-in embedding support."""

from __future__ import annotations
from cortexa.usage.context import usage_action

from typing import List


def _get_llm_config():
    """Load and resolve LLM config."""
    from cortexa.config.llm_providers import _load_yaml_config, _resolve_value
    raw = _load_yaml_config()
    return _resolve_value(raw)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate embeddings using LangChain's OpenAIEmbeddings.

    Automatically uses the configured API key and base URL from config.yaml.
    """
    cfg = _get_llm_config()
    llm_block = cfg.get("llm", {})
    providers = llm_block.get("providers", {})

    # Determine which provider to use for embeddings
    embedding_provider_name = llm_block.get("embedding_provider", "")
    embedding_model = llm_block.get("embedding_model", "text-embedding-3-small")

    # Get the provider config
    prov = None
    if embedding_provider_name and embedding_provider_name in providers:
        prov = providers[embedding_provider_name]
    else:
        # Fallback: find first openai-compatible provider
        for name, p in providers.items():
            if p.get("kind") == "openai":
                embedding_provider_name = name
                prov = p
                break

    if not prov:
        raise ValueError("No OpenAI-compatible provider configured for embeddings")

    # Resolve API key from env
    api_key_ref = prov.get("api_key", "")
    resolved_key = ""
    if api_key_ref.startswith("${") and api_key_ref.endswith("}"):
        import os
        var_name = api_key_ref[2:-1]
        resolved_key = os.getenv(var_name, "")
    elif api_key_ref:
        resolved_key = api_key_ref

    if not resolved_key:
        raise ValueError(f"API Key not configured for embedding provider '{embedding_provider_name}'")

    # Use LangChain's OpenAIEmbeddings
    from langchain_openai import OpenAIEmbeddings

    base_url = prov.get("base_url", "")
    kwargs = {
        "model": embedding_model,
        "api_key": resolved_key,
    }
    if base_url:
        kwargs["base_url"] = base_url

    embeddings = OpenAIEmbeddings(**kwargs)
    from cortexa.usage.collector import AuditedEmbeddingClient
    embeddings.client = AuditedEmbeddingClient(embeddings.client, embedding_provider_name, embedding_model)
    result = embeddings.embed_documents(texts)
    return result


@usage_action("embedding_query", source="knowledge")
def embed_query(text: str) -> List[float]:
    """Generate embedding for a single query text."""
    return embed_texts([text])[0]


def embedding_to_bytes(embedding: List[float]) -> bytes:
    """Convert embedding vector to bytes for storage in PostgreSQL."""
    import struct
    # Pack as array of floats (little-endian)
    return struct.pack(f'{len(embedding)}f', *embedding)


def bytes_to_embedding(data: bytes) -> List[float]:
    """Convert bytes back to embedding vector."""
    import struct
    num_floats = len(data) // 4
    return list(struct.unpack(f'{num_floats}f', data))
