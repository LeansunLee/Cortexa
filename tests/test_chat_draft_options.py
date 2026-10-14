import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from cortexa.api.collaboration import draft_options
from cortexa.db.models import Agent

@pytest.mark.parametrize('kind,enabled,allowed', [
    ('llm', True, ['EXPLICIT_ONLY','ASK_BEFORE_COLLABORATION']),
    ('proxy', False, ['EXPLICIT_ONLY']),
])
def test_draft_options_need_no_conversation_and_respect_workspace_policy(monkeypatch,kind,enabled,allowed):
    agent=Agent(id=uuid.uuid4(),workspace_id=uuid.uuid4(),name='测试',agent_type=kind,collaboration={},proxy_config={'supplemental_prompt':'PRIVATE'})
    require=AsyncMock(return_value=agent)
    monkeypatch.setattr('cortexa.security.access.require_agent_use',require)
    monkeypatch.setattr('cortexa.security.access.actor_required',lambda:SimpleNamespace(has=lambda _:False))
    monkeypatch.setattr('cortexa.api.goals.execution_config',lambda:{'features':{'goal_execution_enabled':True,'goal_collaboration_enabled':True}})
    db=SimpleNamespace(scalar=AsyncMock(return_value={'collaboration':{'max_autonomy':'ASK_BEFORE_COLLABORATION'}}))
    result=asyncio.run(draft_options(agent.id,db))
    assert result['enabled']==enabled
    assert result['allowed_collaboration_modes']==allowed
    assert result['collaboration_mode']=='EXPLICIT_ONLY'
    assert result['supplemental_prompt'] is None
    require.assert_awaited_once_with(db,agent.id)
