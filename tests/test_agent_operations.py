"""Agent maintenance must respect grants, workspace boundaries and Agent-owned memory."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from cortexa.api import agent_operations as ops
from cortexa.api.agents import get_agent_resources
from cortexa.api.knowledge import _can_edit_document, _can_manage
from cortexa.security.access import Actor, current_actor


@pytest.fixture
def actor():
    ws, ident = uuid.uuid4(), uuid.uuid4()
    user = Actor(uuid.uuid4(), 'operator', False, False, 1, workspace_id=ws)
    user.memberships[ws] = {'permissions': {'agent.use', 'agent.operate'}, 'all_agents': False, 'agent_ids': {ident}}
    token = current_actor.set(user)
    yield user, SimpleNamespace(id=ident, workspace_id=ws, status='active', knowledge_base_ids=[])
    current_actor.reset(token)


def database(agent):
    db = AsyncMock()
    db.add = Mock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=agent))
    return db


def test_operation_requires_permission_and_published_grant(actor):
    user, agent = actor
    db = database(agent)
    user.permissions.remove('agent.operate')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ops.get_summary(agent.id, db))
    assert exc.value.status_code == 403
    assert not db.execute.called
    user.permissions.add('agent.operate')
    for field, value in [('status', 'draft'), ('workspace_id', uuid.uuid4()), ('id', uuid.uuid4())]:
        original = getattr(agent, field)
        setattr(agent, field, value)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(ops.get_summary(agent.id, db))
        assert exc.value.status_code == 403
        setattr(agent, field, original)


def test_management_resources_requires_read_permission(actor):
    _, agent = actor
    db = database(agent)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_agent_resources(agent.id, db))
    assert exc.value.status_code == 403
    db.get.assert_not_called()


def test_management_resources_supports_drafts_and_missing_agents(actor):
    user, agent = actor
    user.permissions.add('agent.read')
    agent.status = 'draft'
    db = database(agent)
    db.get.return_value = agent
    with patch.object(ops, 'resource_summary', new=AsyncMock(return_value={'agent': {'id': str(agent.id)}})) as summary:
        result = asyncio.run(get_agent_resources(agent.id, db))
        assert result['agent']['id'] == str(agent.id)
        summary.assert_awaited_once_with(agent, db)
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_agent_resources(agent.id, db))
    assert exc.value.status_code == 404


def test_cross_workspace_capability_is_rejected(actor):
    _, agent = actor
    db = database(agent)
    db.get.return_value = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ops.create_data_binding(agent.id, ops.DataBindingCreate(data_capability_id=db.get.return_value.id), db))
    assert exc.value.status_code == 422
    db.add.assert_not_called()


def test_private_or_foreign_knowledge_cannot_be_bound_as_shared(actor):
    _, agent = actor
    db = database(agent)
    db.execute.side_effect = [Mock(scalar_one_or_none=Mock(return_value=agent)), Mock(scalars=lambda: Mock(all=lambda: []))]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ops.update_knowledge_bindings(agent.id, ops.KnowledgeBindingsUpdate(knowledge_base_ids=[uuid.uuid4()]), db))
    assert exc.value.status_code == 422
    assert agent.knowledge_base_ids == []


def test_memory_archive_cannot_target_another_agent(actor,monkeypatch):
    _, agent = actor
    db=database(agent)
    from cortexa.memory import access
    monkeypatch.setattr(access,'memory_access',AsyncMock(return_value=SimpleNamespace(agent_id=uuid.uuid4())))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ops.archive_agent_memory(agent.id,uuid.uuid4(),db))
    assert exc.value.status_code==404


def test_memory_archive_preserves_record_from_another_creator(actor,monkeypatch):
    _, agent=actor
    from cortexa.memory import access,governance
    mem=SimpleNamespace(id=uuid.uuid4(),agent_id=agent.id,created_by_user_id=uuid.uuid4(),status='active',revision=1)
    db=database(agent)
    monkeypatch.setattr(access,'memory_access',AsyncMock(return_value=mem))
    monkeypatch.setattr(governance,'agent_access',AsyncMock(return_value=agent))
    monkeypatch.setattr(governance,'lock_agent',AsyncMock())
    monkeypatch.setattr(governance,'event',AsyncMock())
    asyncio.run(ops.archive_agent_memory(agent.id,mem.id,db))
    assert mem.status=='archived' and mem.revision==2
    db.delete.assert_not_called()


def test_knowledge_maintenance_is_scoped_to_authorized_private_kb(actor):
    user, _ = actor
    own, other = uuid.uuid4(), uuid.uuid4()
    assert not _can_manage()
    user.operations_knowledge_id = own
    assert _can_manage()
    assert _can_edit_document(SimpleNamespace(knowledge_base_id=own, created_by=uuid.uuid4()))
    assert not _can_edit_document(SimpleNamespace(knowledge_base_id=other, created_by=uuid.uuid4()))


@pytest.mark.parametrize('schema,payload', [(ops.KnowledgeBaseCreate, {'name': '  '}), (ops.MemoryCreate, {'content': '  '}), (ops.MemoryUpdate, {'content': '  '}), (ops.MemoryUpdate, {'content': None}), (ops.MemoryUpdate, {'importance': None})])
def test_invalid_resource_values_rejected(schema, payload):
    with pytest.raises(ValidationError):
        schema(**payload)
