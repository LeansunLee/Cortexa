import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cortexa.runtime.budget_notices import budget_notices, restore_budget_notices
from cortexa.runtime.state import GoalState, UNLIMITED_BUDGET
from cortexa.db.models import ConversationMessage


def test_exact_limits_and_no_disabled_or_unlimited_warning():
    state = GoalState(consumed={'llm_calls': 6, 'tool_iterations': 5, 'agent_calls': 1})
    notices = budget_notices(state)
    assert [(n['field'], n['used'], n['limit'], n['kind']) for n in notices] == [
        ('llm_calls', 6, 6, 'limit'), ('tool_iterations', 5, 5, 'limit')]
    state.limits.web_calls = 0
    state.limits.llm_calls = UNLIMITED_BUDGET
    assert [n['field'] for n in budget_notices(state)] == ['tool_iterations']


def test_reserve_failure_and_duration_are_distinct():
    state = GoalState(consumed={'llm_calls': 5}, budget_phase='FINALIZING',
                      finalization_reserve={'llm_calls': 1})
    assert budget_notices(state)[0]['kind'] == 'reserve'
    state.elapsed_seconds = 180.3
    assert budget_notices(state)[1]['field'] == 'duration'
    state.budget_failure = {'resource': 'tool_calls', 'current': 9, 'requested': 2}
    notice = next(n for n in budget_notices(state) if n['field'] == 'tool_calls')
    assert notice['kind'] == 'insufficient' and notice['requested'] == 2
    state.consumed['output_tokens'] = 16000
    state.finalization_reserve['output_tokens'] = 4096
    notice = next(n for n in budget_notices(state) if n['field'] == 'output_tokens')
    assert notice['reserve'] == 384


def test_historical_notice_matches_exact_final_message(monkeypatch):
    from cortexa.runtime import store
    monkeypatch.setattr(store, 'owned', lambda: [])
    goal, final, previous = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    messages = [ConversationMessage(id=ident, role='assistant', metadata_json={'goal_id':str(goal)})
                for ident in [final, previous]]
    db = SimpleNamespace(scalars=AsyncMock(return_value=[SimpleNamespace(
        state={'result_message_id':str(final), 'limits':{'llm_calls':6}, 'consumed':{'llm_calls':6}})]))
    asyncio.run(restore_budget_notices(db, uuid.uuid4(), messages))
    assert messages[0].metadata_json['budget_notices'][0]['field'] == 'llm_calls'
    assert 'budget_notices' not in messages[1].metadata_json
    assert not db.scalars.call_args.args[0].is_update
