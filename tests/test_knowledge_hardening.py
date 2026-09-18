"""Regressions for workspace boundaries, durable jobs and retrieval coverage."""
import asyncio
import importlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from agentdevstu.api import knowledge
from agentdevstu.api import agents
from agentdevstu.api.schemas import DocumentContentUpdate, KnowledgeBaseStatusUpdate
from agentdevstu.data import doc_storage, document_preview as previews
from agentdevstu.rag import summary
from agentdevstu.security.access import current_actor
from test_doc_summary import document, run_retrieval


def run_as_knowledge_admin(coroutine):
    token = current_actor.set(SimpleNamespace(user_id=uuid.uuid4(), has=lambda _permission: True))
    try:
        return asyncio.run(coroutine)
    finally:
        current_actor.reset(token)


def test_partial_summary_hit_does_not_hide_body_hit(monkeypatch):
    first = document('policy.md', '特殊返利政策摘要')
    second = document('notes.md', '会议纪要')
    context, sources = run_retrieval(monkeypatch, [first, second], '特殊返利政策',
                                    {str(first.id): '特殊返利政策第一部分', str(second.id): '特殊返利政策细则第二部分'})
    assert len(sources) == 2
    assert '第二部分' in context
    assert sources[0]['matched_count'] == 2


def test_generic_documents_not_capped_at_two_or_five(monkeypatch):
    docs = [document(f'政策{i}.txt', '年度返利政策条款') for i in range(12)]
    _, sources = run_retrieval(monkeypatch, docs, '年度返利政策')
    assert len(sources) == 10
    assert sources[0]['matched_count'] == 12
    assert sources[0]['truncated'] is True


@pytest.mark.parametrize('method,path', [
    ('GET', ''), ('DELETE', ''), ('POST', '/search'), ('POST', '/reindex'),
    ('POST', '/documents'), ('POST', '/upload'), ('POST', '/documents/batch-delete'),
    ('POST', '/documents/batch-download'), ('PATCH', '/documents/{doc}/summary'),
    ('POST', '/documents/{doc}/regenerate-summary'), ('PUT', '/documents/{doc}/content'),
    ('POST', '/documents/{doc}/extract'), ('POST', '/documents/{doc}/push'), ('PATCH', '/status'),
])
def test_all_routes_reject_cross_workspace_before_mutating(method, path):
    kb_id, doc_id, workspace = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=kb_id, workspace_id=workspace)
    app = FastAPI()
    app.include_router(knowledge.router)
    app.dependency_overrides[knowledge.get_db] = lambda: db
    with TestClient(app) as client:
        response = client.request(method, f'/knowledge/{kb_id}' + path.format(doc=doc_id),
                                  headers={'X-Workspace-Id': str(uuid.uuid4())}, json={})
    assert response.status_code == 404
    db.commit.assert_not_awaited()
    db.delete.assert_not_awaited()


def test_workspace_is_required():
    app = FastAPI()
    app.include_router(knowledge.router)
    app.dependency_overrides[knowledge.get_db] = lambda: AsyncMock()
    with TestClient(app) as client:
        assert client.get('/knowledge').status_code == 400


def test_ready_pdf_reindex_schedules_index_not_ocr(monkeypatch):
    doc = document('ready.pdf', '摘要', {'extraction_status': 'ready'})
    db, tasks = AsyncMock(), BackgroundTasks()
    db.execute.return_value = Mock(scalars=lambda: Mock(all=lambda: [doc]))
    monkeypatch.setattr(knowledge, '_workspace_kb', AsyncMock())
    asyncio.run(knowledge.reindex_knowledge_base(uuid.uuid4(), tasks, db, 'workspace'))
    assert [task.func for task in tasks.tasks] == [knowledge._safe_index, knowledge._summarize_document]
    assert doc.metadata_json['index_status'] == 'pending'


def test_failed_regeneration_preserves_previous_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_storage, 'DOC_STORAGE_DIR', str(tmp_path))
    doc = document('note.md', '人工确认的摘要', {'summary_source': 'manual'})
    doc_storage.save_document_content(str(doc.id), '内容' * 1000)
    monkeypatch.setattr(knowledge, '_preview_document_record', AsyncMock(return_value=doc))
    monkeypatch.setattr(summary, 'generate_document_summary', AsyncMock(return_value=('截断', 'truncated')))
    with pytest.raises(HTTPException) as error:
        run_as_knowledge_admin(knowledge.regenerate_document_summary(uuid.uuid4(), doc.id, AsyncMock(), None))
    assert error.value.status_code == 502
    assert doc.content == '人工确认的摘要'
    assert doc.metadata_json['summary_status'] == 'error'


def test_concurrent_summary_edit_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_storage, 'DOC_STORAGE_DIR', str(tmp_path))
    doc = document('note.md', '旧摘要')
    doc_storage.save_document_content(str(doc.id), '正文')
    monkeypatch.setattr(knowledge, '_preview_document_record', AsyncMock(return_value=doc))
    async def generate(*args):
        doc.content = '另一个编辑者保存的摘要'
        doc.metadata_json['summary_revision'] = 'new'
        return '生成摘要', 'llm'
    monkeypatch.setattr(summary, 'generate_document_summary', generate)
    with pytest.raises(HTTPException) as error:
        run_as_knowledge_admin(knowledge.regenerate_document_summary(uuid.uuid4(), doc.id, AsyncMock(), None))
    assert error.value.status_code == 409
    assert doc.content == '另一个编辑者保存的摘要'


def test_content_commit_failure_restores_text(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_storage, 'DOC_STORAGE_DIR', str(tmp_path))
    doc = document('note.md', '旧摘要')
    doc_storage.save_document_content(str(doc.id), '旧正文')
    monkeypatch.setattr(knowledge, '_preview_document_record', AsyncMock(return_value=doc))
    db, tasks = AsyncMock(), BackgroundTasks()
    db.commit.side_effect = RuntimeError('commit failed')
    with pytest.raises(HTTPException):
        asyncio.run(knowledge.update_document_content(uuid.uuid4(), doc.id, DocumentContentUpdate(content='新正文'), tasks, db, None))
    assert doc_storage.load_document_content(str(doc.id)) == '旧正文'
    assert not tasks.tasks


def test_edited_text_preview_and_download_use_new_body(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_storage, 'DOC_STORAGE_DIR', str(tmp_path))
    monkeypatch.setattr(previews, 'DOC_STORAGE_DIR', str(tmp_path))
    doc_id = str(uuid.uuid4())
    previews.save_original(doc_id, b'old')
    doc_storage.save_document_content(doc_id, 'new')
    metadata = {'content_revision': '1'}
    assert previews.text_content(doc_id, 'note.md', metadata, '') == 'new'
    assert previews.original_file(doc_id, 'note.md', metadata, '').read_text() == 'new'


def test_search_bounds_and_strategy_validation():
    for payload in [{'query': 'x', 'top_k': 51}, {'query': 'x', 'strategy': 'invalid'}, {'query': ''}]:
        with pytest.raises(ValueError):
            knowledge.SearchRequest(**payload)


def test_selecting_parent_and_child_moves_only_parent():
    parent_id, child_id, sibling_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    folders = {
        parent_id: SimpleNamespace(id=parent_id, parent_id=None),
        child_id: SimpleNamespace(id=child_id, parent_id=parent_id),
        sibling_id: SimpleNamespace(id=sibling_id, parent_id=None),
    }

    assert knowledge._top_level_selected_folder_ids(
        {parent_id, child_id, sibling_id}, folders
    ) == {parent_id, sibling_id}


def test_create_text_document_preserves_markdown_whitespace(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_storage, 'DOC_STORAGE_DIR', str(tmp_path))
    kb_id = uuid.uuid4()
    db, tasks = AsyncMock(), BackgroundTasks()
    kb = SimpleNamespace(id=kb_id)
    db.get.return_value = kb
    db.execute.return_value = Mock(scalars=lambda: Mock(all=lambda: []))
    doc = SimpleNamespace(id=uuid.uuid4(), name='guide.md', content=None, metadata_json=None)
    db.add = Mock(side_effect=lambda value: None)
    db.flush.side_effect = lambda: None
    db.refresh.side_effect = lambda value: None
    # The endpoint only needs a generated document id after flush in the real ORM.
    db.add.side_effect = lambda value: setattr(value, 'id', doc.id)
    original = '\n# 标题\n\n正文\n'
    result = run_as_knowledge_admin(knowledge.create_document(
        kb_id, knowledge.DocumentCreate(name='guide.md', content=original), tasks, db
    ))
    assert result.name == 'guide.md'
    assert doc_storage.load_document_content(str(result.id)) == original
    assert result.metadata_json['size'] == len(original.encode('utf-8'))


def test_knowledge_base_status_schema_accepts_only_toggle_values():
    assert KnowledgeBaseStatusUpdate(status='active').status == 'active'
    assert KnowledgeBaseStatusUpdate(status='disabled').status == 'disabled'
    with pytest.raises(ValueError):
        KnowledgeBaseStatusUpdate(status='archived')


def test_agent_keyword_fallback_excludes_disabled_knowledge_bases():
    db = AsyncMock()
    db.execute.return_value = Mock(scalars=lambda: Mock(all=lambda: []))
    agent = SimpleNamespace(knowledge_base_ids=[str(uuid.uuid4())])

    result = asyncio.run(agents._fallback_keyword_retrieval(agent, {'query': '政策'}, db))

    assert result == ''
    statement = str(db.execute.await_args.args[0])
    assert 'JOIN t_knowledge_bases' in statement
    assert 't_knowledge_bases.status = :status_1' in statement


def test_process_lock_serializes_jobs(tmp_path, monkeypatch):
    from agentdevstu.data import document_jobs
    monkeypatch.setattr(document_jobs, 'DOC_STORAGE_DIR', str(tmp_path))
    events = []
    async def job(number):
        async with document_jobs.document_job_lock('same', 'index'):
            events.append(('start', number))
            await asyncio.sleep(.02)
            events.append(('end', number))
    async def run():
        await asyncio.gather(job(1), job(2))
    asyncio.run(run())
    assert events == [('start', 1), ('end', 1), ('start', 2), ('end', 2)]
