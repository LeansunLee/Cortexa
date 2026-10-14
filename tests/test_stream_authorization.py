"""SSE authorization must tolerate newly invited Agents and reject real revocation."""
import asyncio
import copy
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cortexa.security.access import Actor
from cortexa.security import http


def setup_actor():
    ws, first, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor = Actor(uuid.uuid4(), 'test', False, False, 1, workspace_id=ws)
    actor.memberships[ws] = {'id': uuid.uuid4(), 'permissions': {'agent.use'},
                             'role_ids': [], 'all_agents': False, 'agent_ids': {first, child}}
    actor.runtime_agent_ids.add(first)
    return actor, first, child


def test_inviting_agent_during_poll_is_not_revocation_and_next_poll_checks_it(monkeypatch):
    actor, first, child = setup_actor()
    fresh = copy.deepcopy(actor)
    monkeypatch.setattr(http, 'load_actor', AsyncMock(return_value=fresh))
    checked = []
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def execute(self, statement):
            # Capture the SQL input before a concurrent task adds a collaborator.
            ids = set(statement.compile().params['id_1'])
            checked.append(ids)
            actor.runtime_agent_ids.add(child)
            await asyncio.sleep(0)
            agents = [SimpleNamespace(id=i, workspace_id=actor.workspace_id, status='active') for i in ids]
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: agents))
    monkeypatch.setattr(http, 'async_session_factory', Session)
    async def check():
        reason = await http.stream_authorization_reason(actor, 'token', actor.signature(), '/api/test', True)
        assert reason is None
        assert checked[0] == {first}
        reason = await http.stream_authorization_reason(actor, 'token', actor.signature(), '/api/test', True)
        assert reason is None and checked[1] == {first, child}
        # The child's rights really change while user signature remains stable.
        fresh.memberships[actor.workspace_id]['agent_ids'].remove(child)
        reason = await http.stream_authorization_reason(actor, 'token', fresh.signature(), '/api/test', True)
        assert reason == 'agent_unavailable'
    asyncio.run(check())


@pytest.mark.parametrize('case,expected', [('expired','session_expired'),('permission','authorization_changed'),('agent','agent_unavailable'),('conversation','conversation_unavailable')])
def test_actual_authorization_losses_still_stop_stream(monkeypatch, case, expected):
    actor, first, _ = setup_actor()
    fresh = copy.deepcopy(actor)
    if case == 'permission': fresh.version += 1
    monkeypatch.setattr(http, 'load_actor', AsyncMock(return_value=None if case=='expired' else fresh))
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def scalar(self, *args): return None
        async def execute(self, *args): return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    monkeypatch.setattr(http, 'async_session_factory', Session)
    path=f'/api/conversations/{uuid.uuid4()}/goals/stream' if case=='conversation' else '/api/test'
    assert asyncio.run(http.stream_authorization_reason(actor, 'token', actor.signature(), path, True)) == expected


def test_monitor_database_failure_cancels_and_reports_distinct_chinese_error(monkeypatch):
    actor, _, _ = setup_actor()
    monkeypatch.setattr(http, 'load_actor', AsyncMock(return_value=actor))
    monkeypatch.setattr(http, 'stream_authorization_reason', AsyncMock(side_effect=RuntimeError('PRIVATE_EXCEPTION_DETAIL')))
    sent=[]
    cancelled=[]
    async def app(scope, receive, send):
        await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'text/event-stream')]})
        try: await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    async def send(value): sent.append(value)
    async def receive(): return {'type':'http.request','body':b''}
    scope={'type':'http','method':'GET','scheme':'http','server':('test',80),'path':'/api/test','query_string':b'',
           'headers':[(b'cookie',b'agentdevstu_session=test')]}
    asyncio.run(asyncio.wait_for(http.SecurityMiddleware(app)(scope,receive,send),5))
    assert cancelled
    payload=json.loads(sent[-1]['body'].decode().strip()[6:])
    assert payload['code']=='authorization_check_failed'
    assert '暂时无法核验授权' in payload['error']
    assert 'PRIVATE_EXCEPTION_DETAIL' not in str(sent)
