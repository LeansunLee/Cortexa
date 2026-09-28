"""Deleting personal history must not depend on continued Agent access."""
import os
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
from cortexa.db import models as m
from cortexa.security.access import Actor, current_actor
from cortexa.security.isolation import scope_writes


@pytest.fixture
def actor():
    ws = uuid.uuid4()
    value = Actor(uuid.uuid4(), 'history-owner', False, False, 1,
                  workspace_id=ws, runtime=True,
                  memberships={ws: {'permissions': {'agent.use'}, 'all_agents': False, 'agent_ids': set()}})
    token = current_actor.set(value)
    yield value
    current_actor.reset(token)


def session_for(conv, operation):
    def scalar(statement):
        # The workspace is visible; the old Agent is no longer accessible.
        model = statement.column_descriptions[0]['entity']
        return None if model is m.Agent else object()
    session = SimpleNamespace(new=[], dirty=[], deleted=[], scalar=Mock(side_effect=scalar))
    getattr(session, operation).append(conv)
    return session


def conversation(actor, **changes):
    data = dict(id=uuid.uuid4(), workspace_id=actor.workspace_id, owner_user_id=actor.user_id, agent_id=uuid.uuid4())
    return m.Conversation(**(data | changes))


def test_owner_can_delete_history_with_inaccessible_agent(actor):
    conv = conversation(actor)
    session = session_for(conv, 'deleted')
    scope_writes(session, None, None)
    assert all(call.args[0].column_descriptions[0]['entity'] is not m.Agent for call in session.scalar.call_args_list)


@pytest.mark.parametrize('field', ['owner_user_id', 'workspace_id'])
def test_delete_still_rejects_other_user_or_workspace(actor, field):
    conv = conversation(actor, **{field: uuid.uuid4()})
    with pytest.raises(HTTPException) as error:
        scope_writes(session_for(conv, 'deleted'), None, None)
    assert error.value.status_code == 403


@pytest.mark.parametrize('operation', ['new', 'dirty'])
def test_creating_or_updating_still_requires_agent_access(actor, operation):
    with pytest.raises(HTTPException) as error:
        scope_writes(session_for(conversation(actor), operation), None, None)
    assert error.value.status_code == 403


def test_message_delete_still_checks_its_parent_conversation(actor):
    message = m.ConversationMessage(id=uuid.uuid4(), conversation_id=uuid.uuid4(), role='user', content='test')
    session = SimpleNamespace(new=[], dirty=[], deleted=[message], scalar=Mock(return_value=None))
    with pytest.raises(HTTPException) as error:
        scope_writes(session, None, None)
    assert error.value.status_code == 403
