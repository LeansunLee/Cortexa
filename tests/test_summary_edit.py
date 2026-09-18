"""Manual summary view/edit endpoint regressions."""

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
from fastapi import HTTPException
from fastapi import BackgroundTasks

from agentdevstu.api import knowledge
from agentdevstu.data import doc_storage
from agentdevstu.data import document_preview as previews
from agentdevstu.api.schemas import DocumentSummaryUpdate


@pytest.fixture(autouse=True)
def authorized_knowledge_actor(monkeypatch):
    """Direct endpoint tests supply the actor normally installed by SecurityMiddleware."""
    actor = SimpleNamespace(user_id=uuid.uuid4(), operations_knowledge_id=None, has=lambda _permission: True)
    monkeypatch.setattr(knowledge, "actor_required", lambda: actor)
    return actor


def make_doc(content='LLM 生成摘要'):
    return SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        name='手册.pdf',
        content=content,
        metadata_json={'summary_source': 'llm'},
        valid_until=None,
    )


def test_update_summary_saves_manual_source(monkeypatch):
    doc = make_doc()
    seen = {}

    async def fake_record(kb_id, doc_id, db, workspace_id):
        seen['kb'] = kb_id
        seen['ws'] = workspace_id
        return doc

    monkeypatch.setattr(knowledge, '_preview_document_record', fake_record)
    db = AsyncMock()
    result = asyncio.run(
        knowledge.update_document_summary(
            uuid.uuid4(), doc.id, DocumentSummaryUpdate(content='  手动修正的摘要  '), db, 'ws-1'
        )
    )
    assert result is doc
    assert doc.content == '手动修正的摘要'
    assert doc.metadata_json['summary_source'] == 'manual'
    db.commit.assert_awaited_once()
    assert seen['ws'] == 'ws-1'


def test_update_summary_rejects_whitespace(monkeypatch):
    doc = make_doc()
    monkeypatch.setattr(
        knowledge, '_preview_document_record', AsyncMock(return_value=doc)
    )
    db = AsyncMock()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge.update_document_summary(uuid.uuid4(), doc.id, DocumentSummaryUpdate(content='   '), db, None))
    assert caught.value.status_code == 400
    db.commit.assert_not_awaited()


def test_summary_update_model_bounds():
    with pytest.raises(Exception):
        DocumentSummaryUpdate(content='')
    with pytest.raises(Exception):
        DocumentSummaryUpdate(content='x' * 8001)
    assert DocumentSummaryUpdate(content='x' * 8000).content == 'x' * 8000




# --- Text document create / edit / regenerate -------------------------------


def _setup_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, "DOC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(doc_storage, "DOC_STORAGE_DIR", str(tmp_path))


def _fake_db():
    db = AsyncMock()
    added = []
    db.add = added.append

    async def flush():
        added[-1].id = uuid.uuid4()

    db.flush.side_effect = flush
    db.execute.return_value = Mock(scalars=lambda: Mock(all=lambda: []))
    return db


def test_create_text_document_applies_summary_rule(tmp_path, monkeypatch):
    from agentdevstu.api.schemas import DocumentCreate

    _setup_storage(tmp_path, monkeypatch)
    db = _fake_db()
    tasks = BackgroundTasks()
    short = asyncio.run(knowledge.create_document(
        uuid.uuid4(), DocumentCreate(name="短文.md", content="短内容。" * 10), tasks, db
    ))
    assert short.content == "短内容。" * 10
    assert short.metadata_json["summary_source"] == "full"
    assert [task.func for task in tasks.tasks] == [knowledge._safe_index]
    assert tasks.tasks[0].args == (short.id, short.knowledge_base_id)
    db.commit.assert_awaited_once()

    long_text = "长" * 1500
    long_doc = asyncio.run(knowledge.create_document(
        uuid.uuid4(), DocumentCreate(name="长文.md", content=long_text), tasks, db
    ))
    assert long_doc.content == doc_storage.make_summary(long_text)
    assert long_doc.metadata_json["summary_source"] == "truncated"
    assert any(t.func is knowledge._summarize_document for t in tasks.tasks)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge.create_document(
            uuid.uuid4(), DocumentCreate(name="空.md", content="  "), tasks, db
        ))
    assert caught.value.status_code == 400


def _text_document_doc():
    return SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        name="笔记.md",
        content="旧摘要",
        metadata_json={},
    )


def test_get_content_rejects_non_text(monkeypatch):
    doc = make_doc()
    monkeypatch.setattr(knowledge, "_preview_document_record", AsyncMock(return_value=doc))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge.get_document_content(uuid.uuid4(), doc.id, AsyncMock(), None))
    assert caught.value.status_code == 400


def test_put_content_applies_rule_and_schedules_summary(tmp_path, monkeypatch):
    from agentdevstu.api.schemas import DocumentContentUpdate

    _setup_storage(tmp_path, monkeypatch)
    doc = _text_document_doc()
    monkeypatch.setattr(knowledge, "_preview_document_record", AsyncMock(return_value=doc))
    db = AsyncMock()
    tasks = BackgroundTasks()

    result = asyncio.run(knowledge.update_document_content(
        uuid.uuid4(), doc.id, DocumentContentUpdate(content="新的短内容"), tasks, db, None
    ))
    assert result.content == "新的短内容"
    assert doc.metadata_json["summary_source"] == "full"
    assert doc_storage.load_document_content(str(doc.id)) == "新的短内容"
    assert [task.func for task in tasks.tasks] == [knowledge._safe_index]

    long_text = "详" * 1200
    result = asyncio.run(knowledge.update_document_content(
        uuid.uuid4(), doc.id, DocumentContentUpdate(content=long_text), tasks, db, None
    ))
    assert result.content == doc_storage.make_summary(long_text)
    assert any(t.func is knowledge._summarize_document for t in tasks.tasks)
    assert sum(t.func is knowledge._safe_index for t in tasks.tasks) == 2


def test_create_text_storage_failure_rolls_back_without_tasks(tmp_path, monkeypatch):
    from agentdevstu.api.schemas import DocumentCreate

    _setup_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(knowledge, "save_document_content", Mock(side_effect=OSError("disk full")))
    db = _fake_db()
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge.create_document(
            uuid.uuid4(), DocumentCreate(name="failure.txt", content="content"), tasks, db
        ))
    assert caught.value.status_code == 500
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert tasks.tasks == []


def test_put_content_rejects_non_text(monkeypatch):
    from agentdevstu.api.schemas import DocumentContentUpdate

    doc = make_doc()
    monkeypatch.setattr(knowledge, "_preview_document_record", AsyncMock(return_value=doc))
    with pytest.raises(HTTPException):
        asyncio.run(knowledge.update_document_content(
            uuid.uuid4(), doc.id, DocumentContentUpdate(content="x"), BackgroundTasks(), AsyncMock(), None
        ))


def test_regenerate_summary_follows_rule(tmp_path, monkeypatch):
    _setup_storage(tmp_path, monkeypatch)
    doc = _text_document_doc()
    monkeypatch.setattr(knowledge, "_preview_document_record", AsyncMock(return_value=doc))
    doc_storage.save_document_content(str(doc.id), "短正文")
    db = AsyncMock()
    result = asyncio.run(knowledge.regenerate_document_summary(uuid.uuid4(), doc.id, db, None))
    assert result.content == "短正文"
    assert doc.metadata_json["summary_source"] == "full"

    empty_doc = SimpleNamespace(
        id=uuid.uuid4(), knowledge_base_id=uuid.uuid4(), name="空.md", content="", metadata_json={}
    )
    monkeypatch.setattr(knowledge, "_preview_document_record", AsyncMock(return_value=empty_doc))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(knowledge.regenerate_document_summary(uuid.uuid4(), empty_doc.id, AsyncMock(), None))
    assert caught.value.status_code == 400
