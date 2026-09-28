"""
Document file storage - stores full text in filesystem, summary in DB.
"""
import os
import tempfile
from pathlib import Path

# Base directory for document storage
DOC_STORAGE_DIR = os.environ.get(
    "DOC_STORAGE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "documents"),
)


def _get_doc_dir(doc_id: str) -> Path:
    d = Path(DOC_STORAGE_DIR) / doc_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_document_content(doc_id: str, content: str) -> None:
    """Save full document content to filesystem."""
    doc_dir = _get_doc_dir(doc_id)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=doc_dir, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            temporary.replace(doc_dir / "content.txt")
        finally:
            temporary.unlink(missing_ok=True)


def load_document_content(doc_id: str) -> str | None:
    """Load full document content from filesystem."""
    doc_dir = Path(DOC_STORAGE_DIR) / doc_id
    content_file = doc_dir / "content.txt"
    if content_file.exists():
        return content_file.read_text(encoding="utf-8")
    return None


def delete_document_content(doc_id: str) -> None:
    """Delete document content from filesystem."""
    import shutil
    doc_dir = Path(DOC_STORAGE_DIR) / doc_id
    if doc_dir.exists():
        shutil.rmtree(doc_dir)


def make_summary(content: str, max_len: int = 2000) -> str:
    """Create a summary of document content for DB storage."""
    if not content:
        return ""
    if len(content) <= max_len:
        return content
    return content[:max_len] + "\n...[全文已存储到文件系统]"
