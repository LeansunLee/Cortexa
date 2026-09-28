"""Preview regressions: real PDF/image rendering and paged API responses, no live DB."""

import asyncio
import base64
import io
import os
import uuid
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from datetime import UTC

import pypdfium2 as pdfium
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image

from cortexa.api import knowledge
from cortexa.data import doc_storage
from cortexa.data import document_preview as previews


@pytest.fixture(autouse=True)
def authorized_knowledge_actor(monkeypatch):
    """The router is mounted without the production middleware in these unit tests."""
    actor = SimpleNamespace(user_id=uuid.uuid4(), operations_knowledge_id=None, has=lambda _permission: True)
    monkeypatch.setattr(knowledge, "actor_required", lambda: actor)
    return actor


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, "DOC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(doc_storage, "DOC_STORAGE_DIR", str(tmp_path))
    return tmp_path


def pdf_bytes(pages=3):
    buffer = io.BytesIO()
    with closing(pdfium.PdfDocument.new()) as pdf:
        for i in range(pages):
            pdf.new_page(400 + i * 10, 600).close()
        pdf.save(buffer)
    return buffer.getvalue()


def test_pdf_keeps_original_and_renders_requested_page_only(storage):
    raw = pdf_bytes()
    previews.save_original("doc", raw)
    info = previews.preview_info("doc", "测试.pdf", {}, "")
    assert info["page_count"] == 3 and info["kind"] == "pdf"
    assert not (storage / "doc/preview").exists()
    output = previews.render_page("doc", "pdf", 2)
    assert output.read_bytes().startswith(b"\x89PNG")
    assert [p.name for p in output.parent.iterdir()] == ["pdf-2.png"]
    modified = output.stat().st_mtime_ns
    assert previews.render_page("doc", "pdf", 2).stat().st_mtime_ns == modified
    assert (storage / "doc/original").read_bytes() == raw
    with pytest.raises(IndexError):
        previews.render_page("doc", "pdf", 4)


def test_legacy_pdf_original_recovery_and_text_fallback():
    raw = pdf_bytes(2)
    doc_storage.save_document_content("old-binary", base64.b64encode(raw).decode())
    info = previews.preview_info("old-binary", "old.pdf", {"encoding": "base64"}, "")
    assert info["page_count"] == 2 and info["download_available"]
    doc_storage.save_document_content("old-text", "历史文本内容" * 5000)
    info = previews.preview_info("old-text", "old.pdf", {"encoding": "utf-8"}, "")
    assert info["kind"] == "text" and info["page_count"] == 3
    assert not info["download_available"] and "重新上传" in info["message"]


def test_multipage_image_and_corrupt_file():
    raw = io.BytesIO()
    Image.new("RGB", (80, 50), "red").save(
        raw, format="TIFF", save_all=True, append_images=[Image.new("RGB", (80, 50), "blue")]
    )
    previews.save_original("image", raw.getvalue())
    assert previews.preview_info("image", "扫描.tiff", {}, "")["page_count"] == 2
    image = Image.open(previews.render_page("image", "image", 2))
    assert image.getpixel((0, 0))[:3] == (0, 0, 255)
    previews.save_original("bad", b"not a pdf")
    assert previews.preview_info("bad", "bad.pdf", {}, "")["status"] == "error"


def test_text_encoding_and_safe_svg():
    text = "中文文本与分页" * 5000
    previews.save_original("text", text.encode("gb18030"))
    assert previews.text_content("text", "中文.txt", {}, "") == text
    assert previews.preview_info("text", "中文.txt", {}, "")["page_count"] == 3
    assert previews.file_kind("unsafe.svg", {"content_type": "image/svg+xml"}) == "text"


@pytest.fixture
def client():
    doc_id, kb_id, workspace_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    doc = SimpleNamespace(id=doc_id, name="test.txt", knowledge_base_id=kb_id, metadata_json={}, content="")
    kb = SimpleNamespace(id=kb_id, workspace_id=workspace_id)
    db = AsyncMock()

    async def get(model, object_id):
        return doc if object_id == doc_id else kb if object_id == kb_id else None

    db.get.side_effect = get
    app = FastAPI()
    app.include_router(knowledge.router)
    app.dependency_overrides[knowledge.get_db] = lambda: db
    with TestClient(app, headers={'X-Workspace-Id': str(workspace_id)}) as http:
        yield http, doc, kb


def test_api_text_pages_and_scope(client):
    http, doc, kb = client
    text = "中文abc" * 6001
    previews.save_original(str(doc.id), text.encode())
    base = f"/knowledge/{kb.id}/documents/{doc.id}"
    metadata = http.get(base + "/preview").json()
    assert metadata["page_count"] == 3 and "content" not in metadata
    pages = [http.get(base + f"/pages/{i}").json()["content"] for i in (1, 2, 3)]
    assert "".join(pages) == text and len(pages[0]) == previews.TEXT_PAGE_SIZE
    assert http.get(base + "/pages/0").status_code == 404
    assert http.get(base + "/pages/4").status_code == 404
    assert http.get(base + "/preview", headers={"X-Workspace-Id": str(uuid.uuid4())}).status_code == 404
    assert http.get(f"/knowledge/{uuid.uuid4()}/documents/{doc.id}/preview").status_code == 404
    raw = http.get(base + "/raw")
    assert raw.content == text.encode() and "attachment" in raw.headers["content-disposition"]


def test_api_pdf_page_is_png(client):
    http, doc, kb = client
    doc.name = "paper.pdf"
    previews.save_original(str(doc.id), pdf_bytes(2))
    base = f"/knowledge/{kb.id}/documents/{doc.id}"
    assert http.get(base + "/preview").json()["page_count"] == 2
    page = http.get(base + "/pages/2")
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert http.get(base + "/pages/3").status_code == 404


@pytest.mark.parametrize("name", ["missing.pdf", "missing.txt", "missing.docx"])
@pytest.mark.parametrize("source", ["llm", "manual", "truncated", None])
def test_missing_original_never_previews_or_downloads_summary(client, storage, name, source):
    http, doc, kb = client
    doc.name = name
    doc.content = "这是摘要，不能当作原文件"
    doc.metadata_json = {"summary_source": source, "has_full_content": True, "has_original": True}
    base = f"/knowledge/{kb.id}/documents/{doc.id}"
    info = http.get(base + "/preview").json()
    assert info["status"] == "unsupported"
    assert not info["download_available"]
    assert "缺失" in info["message"]
    assert http.get(base + "/pages/1").status_code == 409
    assert http.get(base + "/raw").status_code == 404
    assert not (storage / str(doc.id) / "original").exists()
    if name.endswith(".txt"):
        assert http.get(base + "/content").status_code == 404


def test_text_preview_and_editor_use_original_even_with_stale_extracted_text(client):
    http, doc, kb = client
    doc.content = "数据库摘要"
    doc.metadata_json = {"summary_source": "llm"}
    text = "完整原文" * 7000
    previews.save_original(str(doc.id), text.encode("gb18030"))
    doc_storage.save_document_content(str(doc.id), "旧提取文本")
    base = f"/knowledge/{kb.id}/documents/{doc.id}"
    info = http.get(base + "/preview").json()
    pages = [http.get(base + f"/pages/{page}").json()["content"] for page in range(1, info["page_count"] + 1)]
    assert "".join(pages) == text
    assert http.get(base + "/content").json()["content"] == text


def test_edited_text_remains_authoritative_and_full_db_text_can_be_recovered(client):
    http, doc, kb = client
    doc.content = "摘要"
    doc.metadata_json = {"summary_source": "llm", "content_revision": "edited"}
    previews.save_original(str(doc.id), b"old original")
    doc_storage.save_document_content(str(doc.id), "编辑后的完整正文")
    base = f"/knowledge/{kb.id}/documents/{doc.id}"
    assert http.get(base + "/pages/1").json()["content"] == "编辑后的完整正文"
    assert http.get(base + "/raw").content.decode() == "编辑后的完整正文"
    assert previews.text_content("legacy", "legacy.txt", {"summary_source": "full"}, "完整短文") == "完整短文"


def test_office_processing_and_cached_conversion(client, monkeypatch):
    http, doc, kb = client
    doc.name = "paper.docx"
    previews.save_original(str(doc.id), b"office fixture")
    started = []
    monkeypatch.setattr(previews, "start_office_preview", lambda *args: started.append(args))
    base = f"/knowledge/{kb.id}/documents/{doc.id}"
    assert http.get(base + "/preview").json()["status"] == "processing"
    assert started == [(str(doc.id), "paper.docx")]
    assert http.get(base + "/pages/1").status_code == 409
    path = previews.pdf_file(str(doc.id), "office")
    path.parent.mkdir()
    path.write_bytes(pdf_bytes(2))
    assert http.get(base + "/preview").json()["page_count"] == 2
    assert http.get(base + "/pages/2").headers["content-type"] == "image/png"


def test_upload_preserves_pdf_original_and_limits(monkeypatch):
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=uuid.uuid4())
    added = []
    db.add = added.append

    async def flush():
        added[-1].id = uuid.uuid4()

    db.flush.side_effect = flush
    db.execute.return_value = Mock(scalars=lambda: Mock(all=lambda: []))
    tasks = BackgroundTasks()
    raw = pdf_bytes(2)
    result = asyncio.run(
        knowledge.upload_document(
            uuid.uuid4(), tasks, UploadFile(filename="test.pdf", file=io.BytesIO(raw)), folder_id=None, db=db
        )
    )
    assert previews.original_file(str(result.id), result.name, result.metadata_json).read_bytes() == raw
    assert result.metadata_json["has_original"] is True
    db.commit.assert_awaited_once()
    assert len(tasks.tasks) == 1
    monkeypatch.setattr(previews, "MAX_UPLOAD_SIZE", 10)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            knowledge.upload_document(
                uuid.uuid4(), tasks, UploadFile(filename="big.txt", file=io.BytesIO(b"x" * 11)), folder_id=None, db=db
            )
        )
    assert caught.value.status_code == 413
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            knowledge.upload_document(
                uuid.uuid4(), tasks, UploadFile(filename="empty.txt", file=io.BytesIO()), folder_id=None, db=db
            )
        )
    assert caught.value.status_code == 400


def test_conversion_failure_is_visible_and_retryable(client):
    http, doc, kb = client
    doc.name = "paper.docx"
    previews.save_original(str(doc.id), b"office fixture")
    (previews.document_dir(str(doc.id)) / "preview-error.json").write_text('{"message": "转换失败"}')
    base = f"/knowledge/{kb.id}/documents/{doc.id}"
    assert http.get(base + "/preview").json()["status"] == "error"


def test_delete_storage_removes_original_and_previews(storage):
    previews.save_original("delete-me", pdf_bytes(1))
    previews.render_page("delete-me", "pdf", 1)
    doc_storage.delete_document_content("delete-me")
    assert not (storage / "delete-me").exists()


def test_document_response_allows_legacy_null_metadata():
    from datetime import datetime, timezone

    from cortexa.api.schemas import DocumentOut

    response = DocumentOut.model_validate(
        {
            "id": uuid.uuid4(),
            "knowledge_base_id": uuid.uuid4(),
            "name": "legacy.txt",
            "content": "legacy",
            "status": "active",
            "created_at": datetime.now(UTC),
            "metadata_json": None,
        }
    )
    assert response.metadata_json is None
