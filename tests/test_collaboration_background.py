import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from cortexa.collaboration.background import prepare_background
from cortexa.collaboration.drafts import CollaborationDraft, proxy_request
from cortexa.collaboration.schemas import AgentHandoff


def session(rows):
    return SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))))


@pytest.mark.parametrize('legacy_mode', ['auto', 'none', 'manual'])
def test_proxy_never_reads_context_or_calls_model(monkeypatch, legacy_mode):
    monkeypatch.setattr('cortexa.config.llm_providers.create_llm', lambda *a: pytest.fail('must not call selector model'))
    db = session([])
    draft = CollaborationDraft(agent_id=uuid.uuid4(), task='本轮任务', context_mode=legacy_mode, context_text='旧手动背景')
    result = asyncio.run(prepare_background(db, uuid.uuid4(), draft, '主对话内容', target_type='proxy'))
    db.execute.assert_not_called()
    assert result['facts'] == []
    assert result['mode'] == 'none'
    handoff = AgentHandoff(source_agent_id='s', target_agent_id='t', task='本轮任务', question='本轮任务',
        background_context={'facts':[{'quote':'私有历史'}]}, dependency_results=[{'result':'前置结果'}], known_facts=['已知事实'])
    request = proxy_request(handoff)
    assert '本轮任务' in request
    assert all(value not in request for value in ('私有历史','前置结果','已知事实'))


@pytest.mark.parametrize('legacy_mode', ['auto', 'none', 'manual'])
def test_llm_always_gets_chronological_context_without_selector(monkeypatch, legacy_mode):
    monkeypatch.setattr('cortexa.config.llm_providers.create_llm', lambda *a: pytest.fail('must not call selector model'))
    db = session([SimpleNamespace(id='new', role='assistant', content='答复'), SimpleNamespace(id='old', role='user', content='历史问题')])
    draft = CollaborationDraft(agent_id=uuid.uuid4(), task='本轮任务', context_mode=legacy_mode, context_text='旧手动背景')
    result = asyncio.run(prepare_background(db, uuid.uuid4(), draft, '主输入', target_type='llm', attachments=['附件正文']))
    assert result['status'] == 'ready'
    assert result['mode'] == 'conversation'
    assert [f['quote'] for f in result['facts']] == ['历史问题', '答复', '主输入', '附件正文']
    db.execute.assert_awaited_once()


def test_context_is_bounded_and_current_message_is_excluded_from_history_query():
    rows = [SimpleNamespace(id=str(i), role='user', content='字'*10000) for i in range(12)]
    db = session(rows)
    excluded = uuid.uuid4()
    result = asyncio.run(prepare_background(db, uuid.uuid4(), target_type='llm', exclude_message_id=excluded))
    assert sum(len(f['quote']) for f in result['facts']) <= 14000
    assert all(f['truncated'] for f in result['facts'])
    assert excluded in db.execute.call_args.args[0].compile().params.values()


def test_empty_context_still_runs_and_db_failure_is_not_silently_ignored():
    result = asyncio.run(prepare_background(session([]), uuid.uuid4(), target_type='llm'))
    assert result['status'] == 'ready' and result['facts'] == []
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError('database unavailable')))
    with pytest.raises(RuntimeError):
        asyncio.run(prepare_background(db, uuid.uuid4(), target_type='llm'))
