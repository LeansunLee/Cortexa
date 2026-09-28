import uuid
import pytest
from cortexa.collaboration.drafts import CollaborationDraft, validate_drafts, proxy_request, visible_snapshot
from cortexa.collaboration.schemas import AgentHandoff
from cortexa.agents.proxy_executor import build_proxy_body


def test_dependency_order_and_invalid_references():
    first = CollaborationDraft(agent_id=uuid.uuid4(), task='查数据')
    second = CollaborationDraft(agent_id=uuid.uuid4(), task='制定计划', depends_on=[first.agent_id])
    validate_drafts([first, second])
    for values in ([second, first], [first, first], [second]):
        with pytest.raises(ValueError):
            validate_drafts(values)
    with pytest.raises(ValueError):
        CollaborationDraft(agent_id=first.agent_id, task='  ')


def test_proxy_override_matches_preview_and_does_not_change_config():
    cfg = {'supplemental_prompt': '默认', 'request_mapping': {'query': '$.input'}}
    handoff = AgentHandoff(source_agent_id='source', target_agent_id='target', task='修改后的任务', question='修改后的任务', constraints=['必须真实'], dependency_results=[{'result': '交付100台'}])
    request = proxy_request(handoff)
    assert '修改后的任务' in request and '交付100台' not in request and '必须真实' in request
    assert build_proxy_body(cfg, {'input': request})['query'].startswith('默认\n\n')
    assert build_proxy_body(cfg, {'input': request}, '')['query'] == request
    assert build_proxy_body(cfg, {'input': request}, '本轮')['query'].startswith('本轮\n\n')
    assert cfg['supplemental_prompt'] == '默认'


def test_snapshot_redacts_credentials():
    assert visible_snapshot({'request_body': {'query': '正常', 'api_key': 'private'}})['request_body'] == {'query': '正常', 'api_key': '[已隐藏]'}


def test_runtime_user_cannot_read_agent_configuration():
    from types import SimpleNamespace
    from cortexa.security.access import current_actor
    token = current_actor.set(SimpleNamespace(has=lambda permission: False))
    try:
        result = visible_snapshot({'type': 'llm', 'messages': [{'role':'system', 'content':'私有规则'}]})
        assert 'messages' not in result
        assert 'notice' in result
    finally:
        current_actor.reset(token)


def test_snapshot_file_roundtrip_and_conversation_isolation(monkeypatch, tmp_path):
    import asyncio
    from cortexa.collaboration import drafts
    monkeypatch.setattr(drafts, '__file__', str(tmp_path / 'src' / 'cortexa' / 'collaboration' / 'drafts.py'))
    async def run():
        conversation_id = uuid.uuid4()
        snapshot = {'type': 'proxy', 'request_body': {'query': '完整输入' * 5000}}
        reference = await drafts.save_input_snapshot(conversation_id, snapshot)
        assert 'request_body' not in reference
        assert await drafts.read_input_snapshot(conversation_id, reference['snapshot_id']) == snapshot
        with pytest.raises(FileNotFoundError):
            await drafts.read_input_snapshot(uuid.uuid4(), reference['snapshot_id'])
    asyncio.run(run())
