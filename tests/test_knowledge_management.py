"""Batch delete and Agent-to-workspace copy regressions without a live database."""

import asyncio
import os
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
import pytest
from fastapi import BackgroundTasks, HTTPException, Response

from cortexa.api import knowledge
from cortexa.data import doc_storage
from cortexa.data import document_preview as previews
from cortexa.api.schemas import DocumentValidityUpdate


@pytest.fixture(autouse=True)
def authorized_knowledge_actor(monkeypatch):
    """Exercise document operations as an explicitly authorized workspace actor."""
    actor = SimpleNamespace(user_id=uuid.uuid4(), operations_knowledge_id=None, has=lambda _permission: True)
    monkeypatch.setattr(knowledge, "actor_required", lambda: actor)
    return actor


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, "DOC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(doc_storage, "DOC_STORAGE_DIR", str(tmp_path))
    ws = uuid.uuid4()
    source_kb = SimpleNamespace(id=uuid.uuid4(), workspace_id=ws, agent_id=uuid.uuid4())
    target = SimpleNamespace(id=uuid.uuid4(), workspace_id=ws, agent_id=None)
    source = SimpleNamespace(
        id=uuid.uuid4(), name="note.txt", knowledge_base_id=source_kb.id, content="摘要", metadata_json={"size": 12}
    )
    previews.save_original(str(source.id), b"original bytes")
    doc_storage.save_document_content(str(source.id), "完整正文内容")
    db = AsyncMock()
    db.get.side_effect = lambda model, ident: (
        source_kb if ident == source_kb.id else source if ident == source.id else None
    )
    db.add = Mock()
    target_result = Mock()
    target_result.scalar_one_or_none.return_value = target
    existing_result = Mock()
    existing_result.scalars.return_value.first.return_value = None
    db.execute.side_effect = [target_result, existing_result]
    return db, source_kb, target, source, tmp_path, existing_result


def push(setup):
    db, source_kb, target, source, *_ = setup
    response, background = Response(), BackgroundTasks()
    doc = asyncio.run(
        knowledge.push_document_to_workspace(
            source_kb.id,
            source.id,
            knowledge.PushDocument(target_kb_id=target.id),
            response,
            background,
            db,
            str(source_kb.workspace_id),
        )
    )
    return doc, response, background


def test_push_preserves_original_and_full_text(setup):
    db, source_kb, target, source, root, _ = setup
    copied, _, tasks = push(setup)
    assert copied.id != source.id and copied.knowledge_base_id == target.id
    assert (root / str(copied.id) / "original").read_bytes() == b"original bytes"
    assert (root / str(copied.id) / "content.txt").read_text() == "完整正文内容"
    assert (root / str(source.id) / "original").read_bytes() == b"original bytes"
    assert copied.metadata_json["pushed_from_document_id"] == str(source.id)
    assert len(tasks.tasks) == 1
    db.commit.assert_awaited_once()


def test_update_validity_keeps_document_and_accepts_permanent_or_date(setup):
    db, kb, _, source, *_ = setup
    source.valid_until = None
    db.get.side_effect = lambda model, ident: kb if ident == kb.id else source if ident == source.id else None

    updated = asyncio.run(knowledge.update_document_validity(
        kb.id, source.id, DocumentValidityUpdate(valid_until=date(2026, 12, 31)), db, str(kb.workspace_id)
    ))

    assert updated is source and source.valid_until == date(2026, 12, 31)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(source)


def test_repeat_push_returns_existing_without_copy(setup):
    db, _, target, _, root, existing_result = setup
    existing = SimpleNamespace(id=uuid.uuid4(), knowledge_base_id=target.id)
    existing_result.scalars.return_value.first.return_value = existing
    result, response, tasks = push(setup)
    assert result is existing and response.status_code == 200 and not tasks.tasks
    assert len(list(root.iterdir())) == 1
    db.add.assert_not_called()


@pytest.mark.parametrize("invalid", ["source_public", "target_private", "target_other_workspace", "wrong_workspace"])
def test_push_enforces_source_target_scopes(setup, invalid):
    db, source_kb, target, source, root, _ = setup
    if invalid == "source_public":
        source_kb.agent_id = None
    if invalid == "target_private":
        target.agent_id = uuid.uuid4()
    if invalid == "target_other_workspace":
        target.workspace_id = uuid.uuid4()
    if invalid == "wrong_workspace":
        db.get.side_effect = lambda *_: None
    with pytest.raises(HTTPException):
        push(setup)
    db.add.assert_not_called()
    assert len(list(root.iterdir())) == 1


def test_push_copy_failure_rolls_back_and_keeps_source(setup, monkeypatch):
    db, _, _, source, root, _ = setup

    def fail(source, destination):
        (root / destination).mkdir()
        raise OSError("disk full")

    monkeypatch.setattr(knowledge, "_copy_document_files", fail)
    with pytest.raises(HTTPException) as error:
        push(setup)
    assert error.value.status_code == 500
    db.rollback.assert_awaited_once()
    assert [p.name for p in root.iterdir()] == [str(source.id)]


def test_batch_delete_validates_all_ids_before_deleting(setup):
    db, kb, _, source, root, _ = setup
    result = Mock()
    result.scalars.return_value.all.return_value = [source]
    db.execute.side_effect = None
    db.execute.return_value = result
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            knowledge.batch_delete_documents(
                kb.id, knowledge.BatchDeleteDocuments(document_ids=[source.id, uuid.uuid4()]), db, str(kb.workspace_id)
            )
        )
    assert error.value.status_code == 409
    db.delete.assert_not_awaited()
    assert (root / str(source.id) / "original").exists()


def test_batch_delete_deduplicates_selection_and_cleans_files(setup):
    db, kb, _, source, root, _ = setup
    result = Mock()
    result.scalars.return_value.all.return_value = [source]
    db.execute.side_effect = None
    db.execute.return_value = result
    response = asyncio.run(
        knowledge.batch_delete_documents(
            kb.id, knowledge.BatchDeleteDocuments(document_ids=[source.id, source.id]), db, str(kb.workspace_id)
        )
    )
    assert response["deleted_count"] == 1
    db.delete.assert_awaited_once_with(source)
    db.commit.assert_awaited_once()
    assert not (root / str(source.id)).exists()


def test_batch_commit_failure_retains_files(setup):
    db, kb, _, source, root, _ = setup
    result = Mock()
    result.scalars.return_value.all.return_value = [source]
    db.execute.side_effect = None
    db.execute.return_value = result
    db.commit.side_effect = RuntimeError("DB failed")
    with pytest.raises(RuntimeError):
        asyncio.run(
            knowledge.batch_delete_documents(
                kb.id, knowledge.BatchDeleteDocuments(document_ids=[source.id]), db, str(kb.workspace_id)
            )
        )
    assert (root / str(source.id) / "original").exists()


def test_download_archive_original_bytes_safe_unique_names(setup):
    import zipfile
    _, _, _, source, _, _ = setup
    source.name = '../中文.txt'
    other = SimpleNamespace(**{**vars(source), 'name': r'C:\中文.txt'})
    temporary, archive = knowledge._build_download_archive([source, other, source])
    try:
        with zipfile.ZipFile(archive) as zipped:
            assert zipped.namelist() == ['中文.txt', '中文 (2).txt', '中文 (3).txt']
            assert all(zipped.read(name) == b'original bytes' for name in zipped.namelist())
    finally:
        temporary.cleanup()
    assert not archive.exists()


def test_download_missing_original_cleans_archive(setup, monkeypatch):
    _, _, _, source, root, _ = setup
    monkeypatch.setattr(previews, 'original_file', lambda *args: None)
    monkeypatch.setattr(knowledge.tempfile, 'tempdir', str(root))
    with pytest.raises(HTTPException) as error:
        knowledge._build_download_archive([source])
    assert error.value.status_code == 409
    assert not list(root.glob('knowledge-download-*'))


def test_batch_download_validates_membership(setup):
    db, kb, _, source, _, _ = setup
    result = Mock()
    result.scalars.return_value.all.return_value = [source]
    db.execute.side_effect = None
    db.execute.return_value = result
    with pytest.raises(HTTPException) as error:
        asyncio.run(knowledge.batch_download_documents(kb.id, knowledge.BatchDeleteDocuments(document_ids=[source.id, uuid.uuid4()]), db, str(kb.workspace_id)))
    assert error.value.status_code == 409


def test_batch_download_deduplicates_and_cleans_after_response(setup):
    import zipfile
    db, kb, _, source, _, _ = setup
    result = Mock()
    result.scalars.return_value.all.return_value = [source]
    db.execute.side_effect = None
    db.execute.return_value = result
    response = asyncio.run(knowledge.batch_download_documents(kb.id, knowledge.BatchDeleteDocuments(document_ids=[source.id, source.id]), db, str(kb.workspace_id)))
    with zipfile.ZipFile(response.path) as zipped:
        assert zipped.namelist() == ['note.txt']
    asyncio.run(response.background())
    assert not response.path.exists()
