"""Document chunking service - splits documents into manageable chunks for RAG."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class Chunk:
    content: str
    index: int
    token_count: int
    metadata: dict | None = None


def estimate_tokens(text: str) -> int:
    """Rough token count estimation (1 token ≈ 4 chars for Chinese/English mix)."""
    return max(1, len(text) // 3)


def chunk_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 128,
    separators: List[str] | None = None,
) -> List[Chunk]:
    """Split text into overlapping chunks using recursive character splitting.

    Args:
        text: The full document text
        chunk_size: Target chunk size in characters
        chunk_overlap: Overlap between consecutive chunks
        separators: Priority list of separators to split on

    Returns:
        List of Chunk objects
    """
    if not text or not text.strip():
        return []

    if separators is None:
        separators = ["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", "，", ",", " "]

    chunks = []
    _split_recursive(text, separators, 0, chunk_size, chunk_overlap, chunks)
    return chunks


def _split_recursive(
    text: str,
    separators: List[str],
    index: int,
    chunk_size: int,
    chunk_overlap: int,
    result: List[Chunk],
) -> int:
    """Recursively split text and return next chunk index."""
    text = text.strip()
    if not text:
        return index

    # If text fits in one chunk, add it directly
    if len(text) <= chunk_size:
        result.append(Chunk(
            content=text,
            index=index,
            token_count=estimate_tokens(text),
        ))
        return index + 1

    # Try each separator
    for sep in separators:
        if sep not in text:
            continue

        parts = text.split(sep)
        current = ""

        for i, part in enumerate(parts):
            candidate = current + (sep if current else "") + part

            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current.strip():
                    result.append(Chunk(
                        content=current.strip(),
                        index=index,
                        token_count=estimate_tokens(current.strip()),
                    ))
                    index += 1
                current = part

        # Handle remaining text
        if current.strip():
            if len(current) > chunk_size:
                # Recursively split with remaining separators
                remaining_seps = separators[separators.index(sep) + 1:]
                if remaining_seps:
                    index = _split_recursive(current, remaining_seps, index, chunk_size, chunk_overlap, result)
                else:
                    # Last resort: hard split
                    for i in range(0, len(current), chunk_size - chunk_overlap):
                        chunk_text = current[i:i + chunk_size]
                        if chunk_text.strip():
                            result.append(Chunk(
                                content=chunk_text.strip(),
                                index=index,
                                token_count=estimate_tokens(chunk_text.strip()),
                            ))
                            index += 1
            else:
                result.append(Chunk(
                    content=current.strip(),
                    index=index,
                    token_count=estimate_tokens(current.strip()),
                ))
                index += 1

        return index

    # No separator found, hard split
    for i in range(0, len(text), chunk_size - chunk_overlap):
        chunk_text = text[i:i + chunk_size]
        if chunk_text.strip():
            result.append(Chunk(
                content=chunk_text.strip(),
                index=index,
                token_count=estimate_tokens(chunk_text.strip()),
            ))
            index += 1

    return index
