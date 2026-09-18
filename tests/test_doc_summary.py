"""LLM document summaries and two-stage knowledge retrieval regressions."""

import asyncio
import io
import importlib
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
from fastapi import BackgroundTasks
from fastapi import UploadFile

from agentdevstu.agents.knowledge import _build_query_context, _score_text, retrieve_knowledge
from agentdevstu.api import knowledge
from agentdevstu.config import llm_providers
from agentdevstu.data import doc_storage
from agentdevstu.data import document_preview as previews
db_engine = importlib.import_module("agentdevstu.db.engine")
from agentdevstu.rag import summary as doc_summary
from agentdevstu.rag.summary import generate_document_summary


@pytest.fixture(autouse=True)
def authorized_knowledge_actor(monkeypatch):
    """Direct service tests run with the same explicit actor contract as HTTP requests."""
    actor = SimpleNamespace(user_id=uuid.uuid4(), operations_knowledge_id=None, has=lambda _permission: True)
    monkeypatch.setattr(knowledge, "actor_required", lambda: actor)
    return actor


class FakeLLM:
    def __init__(self, content):
        self._content = content
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self._content)


def document(name, content, metadata=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        name=name,
        content=content,
        metadata_json=metadata or {},
    )


def run_retrieval(monkeypatch, documents, query, full_texts=None):
    agent = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4(), knowledge_base_ids=[])
    database = SimpleNamespace(
        execute=AsyncMock(return_value=Mock(scalars=lambda: Mock(all=lambda: documents)))
    )
    store = full_texts or {}
    monkeypatch.setattr(doc_storage, "load_document_content", lambda identifier: store.get(identifier))
    sources = []
    context = asyncio.run(retrieve_knowledge(agent, query, database, sources=sources))
    return context, sources


# --- LLM summary generation -------------------------------------------------


def test_generate_summary_uses_llm_and_reports_source(monkeypatch):
    fake = FakeLLM("黑旗600 用户手册摘要：涵盖仪表、保养与常见故障。")
    monkeypatch.setattr(llm_providers, "create_llm", lambda name=None: fake)
    text = "黑旗600 摩托车用户手册正文，涵盖保养规范与参数表。" * 40
    value, source = asyncio.run(generate_document_summary("黑旗600手册.pdf", text))
    assert value.startswith("黑旗600") and source == "llm"
    assert len(fake.calls) == 1


def test_generate_summary_short_document_returns_full_text(monkeypatch):
    fake = FakeLLM("不应被调用")
    monkeypatch.setattr(llm_providers, "create_llm", lambda name=None: fake)
    text = "短文档全文，直接作为摘要。" * 10
    value, source = asyncio.run(generate_document_summary("短文.md", text))
    assert value == text.strip() and source == "full"
    assert fake.calls == []


def test_generate_summary_long_input_keeps_head_and_tail(monkeypatch):
    fake = FakeLLM('摘要')
    monkeypatch.setattr(llm_providers, "create_llm", lambda name=None: fake)
    text = "头" * doc_summary.SUMMARY_MAX_INPUT_CHARS + "中" * 5000 + "尾" * 2000
    _, source = asyncio.run(generate_document_summary("长手册.pdf", text))
    assert source == "llm"
    sent = fake.calls[0][0]['content']
    assert "…[中间内容省略]…" in sent
    assert sent.rstrip().endswith("尾")


def test_generate_summary_falls_back_to_truncation_on_failure(monkeypatch):
    def broken(name=None):
        raise RuntimeError('provider down')

    monkeypatch.setattr(llm_providers, "create_llm", broken)
    text = "正文内容。" * 500
    value, source = asyncio.run(generate_document_summary("手册.pdf", text))
    assert source == "truncated"
    assert value.startswith('正文内容')
    assert "…[全文已存储到文件系统]" in value or value == doc_storage.make_summary(text)


def test_generate_summary_empty_content_is_noop(monkeypatch):
    value, source = asyncio.run(generate_document_summary("空.pdf", "   "))
    assert value == '' and source == 'truncated'


# --- Two-stage retrieval ----------------------------------------------------


def test_summary_locates_document_and_full_text_supplies_passage(monkeypatch):
    doc = document('黑旗600用户手册.pdf', '黑旗600 用户手册：涵盖仪表、保养与保修政策。')
    full = "黑旗600 用户手册。前段目录。" + "无关内容。" * 300 + "机油容量为 1.2 升。附录完毕。"
    context, sources = run_retrieval(monkeypatch, [doc], '黑旗600机油容量', full_texts={str(doc.id): full})
    assert "机油容量为 1.2 升" in context
    assert sources[0]["document_id"] == str(doc.id)


def test_summary_miss_falls_back_to_full_text_scan(monkeypatch):
    doc = document('车型参数表.pdf', '本表整理各车型基础参数，供销售参考。')
    full = '金吉拉250 CVT 版led大灯与USB接口参数齐全。' * 50
    context, sources = run_retrieval(monkeypatch, [doc], '金吉拉250 led大灯', full_texts={str(doc.id): full})
    assert "金吉拉250" in context
    assert len(sources) == 1


def test_stage_two_skips_empty_full_text_but_keeps_summary_hit(monkeypatch):
    doc = document('黑旗600政策.pdf', '黑旗600 销售政策摘要。')
    context, sources = run_retrieval(monkeypatch, [doc], '黑旗600销售政策', full_texts={str(doc.id): None})
    assert "黑旗600 销售政策摘要" in context
    assert len(sources) == 1


def test_score_text_prefers_title_mentions():
    ctx = _build_query_context('黑旗600的定价政策返利补贴')
    target = _score_text('黑旗600价格签批.pdf', '32800 元', ctx)
    other = _score_text('灰石300政策返利补贴.pdf', '定价政策返利补贴黑旗', ctx)
    assert target > other


# --- Upload wiring ----------------------------------------------------------


def test_txt_upload_schedules_summary_and_index(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, "DOC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(doc_storage, "DOC_STORAGE_DIR", str(tmp_path))
    db = AsyncMock()
    added = []
    db.add = added.append

    async def flush():
        added[-1].id = uuid.uuid4()

    db.flush.side_effect = flush
    db.execute.return_value = Mock(scalars=lambda: Mock(all=lambda: []))
    tasks = BackgroundTasks()
    result = asyncio.run(
        knowledge.upload_document(
            uuid.uuid4(),
            tasks,
            UploadFile(filename="note.txt", file=io.BytesIO("正文".encode())),
            folder_id=None,
            db=db,
        )
    )
    scheduled = [task.func for task in tasks.tasks]
    assert knowledge._safe_index in scheduled
    assert knowledge._summarize_document in scheduled
    assert result.metadata_json["has_full_content"] is True


def test_background_summary_updates_content_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, "DOC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(doc_storage, "DOC_STORAGE_DIR", str(tmp_path))
    doc = document('手册.pdf', '旧截断摘要', metadata={'extraction_status': 'ready'})
    doc_storage.save_document_content(str(doc.id), '完整正文内容，用于生成摘要。')

    class FakeSession:
        committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, model, ident):
            return doc

        async def refresh(self, obj, **kwargs):
            pass

        async def commit(self):
            self.committed = True

    session = FakeSession()
    monkeypatch.setattr(db_engine, 'async_session_factory', lambda: session)
    monkeypatch.setattr(doc_summary, 'generate_document_summary', AsyncMock(return_value=('LLM 摘要', 'llm')))
    asyncio.run(knowledge._summarize_document(doc.id))
    assert doc.content == 'LLM 摘要'
    assert doc.metadata_json['summary_source'] == 'llm'
    assert session.committed is True


def test_pdf_processing_stores_llm_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, "DOC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(doc_storage, "DOC_STORAGE_DIR", str(tmp_path))
    doc = document('manual.pdf', '', metadata={'extraction_status': 'processing'})
    previews.save_original(str(doc.id), b'%PDF-1.4 fake')

    class FakeSession:
        def __init__(self):
            self.doc = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, model, ident):
            return doc

        async def refresh(self, obj, **kwargs):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    session = FakeSession()
    monkeypatch.setattr(db_engine, 'async_session_factory', lambda: session)
    from agentdevstu.data import pdf_extraction

    def fake_extract(path):
        return 'PDF 全文内容。' * 10, 0

    monkeypatch.setattr(pdf_extraction, 'extract_pdf', fake_extract)
    monkeypatch.setattr(doc_summary, 'generate_document_summary', AsyncMock(return_value=('PDF 摘要', 'llm')))
    monkeypatch.setattr(knowledge, '_safe_index', AsyncMock())
    asyncio.run(knowledge._process_pdf_impl(doc.id, uuid.uuid4()))
    assert doc.content == 'PDF 摘要'
    assert doc.metadata_json['extraction_status'] == 'ready'
    assert doc.metadata_json['summary_source'] == 'llm'
