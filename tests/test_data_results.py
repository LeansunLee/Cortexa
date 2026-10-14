import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from cortexa.api import data_results as api


def observation(action):
    return {'source_type': 'DATA', 'source_id': 'data:' + str(uuid.uuid4()),
            'action_id': str(action), 'status': 'PARTIAL', 'raw_result': {
                'data': [{'车型': '<script>bad()</script>', '数量': i} for i in range(511)],
                'row_count': 900, 'truncated': True}, 'private': 'SECRET'}


def test_exact_child_lookup_and_page():
    action = uuid.uuid4()
    obs = observation(action)
    snapshot = {'agent_runs': {'child': {'state': {'runtime_agent_id': 'child-agent'},
                                       'payload': {'observations': [obs]}}}}
    agent, found = api.find_result(snapshot, 'parent', action)
    assert agent == 'child-agent'
    assert api.find_result(snapshot, 'parent', uuid.uuid4()) is None
    result = api.result_page(found, 500, 50)
    assert len(result['rows']) == 11
    assert result['returned_rows'] == 511
    assert result['row_count'] == 900 and result['truncated']
    assert 'SECRET' not in json.dumps(result)
    obs['raw_result'] = json.dumps(obs['raw_result'])
    assert len(api.result_page(obs, 0, 50)['rows']) == 50
    assert api.result_page({'facts': [], 'status': 'EMPTY'}, 0, 50)['rows'] == []


@pytest.mark.parametrize('failure', ['owner', 'agent', 'binding', 'missing', None])
def test_endpoint_current_access_and_archived_content(monkeypatch, failure):
    action, agent_id = uuid.uuid4(), uuid.uuid4()
    db = SimpleNamespace(scalars=AsyncMock(return_value=[SimpleNamespace(
        id=uuid.uuid4(), agent_id=agent_id, artifacts={'snapshot': {}})]),
        scalar=AsyncMock(return_value=None if failure == 'binding' else uuid.uuid4()))
    class Session:
        async def __aenter__(self): return db
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(api, 'async_session_factory', Session)
    own = AsyncMock(side_effect=HTTPException(404) if failure == 'owner' else None)
    monkeypatch.setattr(api, 'own_conversation', own)
    monkeypatch.setattr(api, 'owned', lambda: [])
    check = AsyncMock(return_value=SimpleNamespace(id=agent_id, workspace_id=uuid.uuid4()),
                      side_effect=HTTPException(403) if failure == 'agent' else None)
    monkeypatch.setattr(api, 'require_agent_use', check)
    monkeypatch.setattr(api.ArtifactStore, 'read', lambda *args: {
        'observations': [] if failure == 'missing' else [observation(action)]})
    if failure:
        with pytest.raises(HTTPException):
            asyncio.run(api.get_data_result(uuid.uuid4(), action, 0, 50))
        if failure == 'owner': check.assert_not_awaited()
    else:
        result = asyncio.run(api.get_data_result(uuid.uuid4(), action, 0, 50))
        assert result.headers['cache-control'] == 'no-store'
        assert len(json.loads(result.body)['rows']) == 50
        check.assert_awaited_once_with(db, agent_id)
