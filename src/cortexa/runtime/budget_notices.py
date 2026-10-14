"""Public budget facts derived from counters, independent of model wording."""
from cortexa.runtime.state import UNLIMITED_BUDGET

LABELS = {
    'duration': '执行时长', 'llm_calls': '模型调用次数', 'tool_calls': '工具调用次数',
    'tool_iterations': '工具执行轮次', 'web_calls': '网页搜索次数',
    'agent_calls': '协作调用次数', 'max_collaborators': '协作参与者数量',
    'agent_depth': '协作深度', 'context_tokens': '上下文预算',
    'output_tokens': '输出预算', 'max_steps': '执行步骤数',
    'max_replans': '重新规划次数', 'max_failures': '失败次数',
}


def budget_notices(state):
    if hasattr(state, 'model_dump'):
        state = state.model_dump(mode='json')
    limits, consumed = state.get('limits', {}), dict(state.get('consumed', {}))
    consumed['duration'] = state.get('elapsed_seconds', 0)
    failure = state.get('budget_failure') or {}
    if failure.get('resource') in LABELS:
        key = failure['resource']
        consumed[key] = max(consumed.get(key, 0), failure.get('current', 0))
    result = []
    for key, used in consumed.items():
        limit = limits.get(key)
        if key not in LABELS or not isinstance(limit, (int, float)) or limit >= UNLIMITED_BUDGET:
            continue
        # Disabled capabilities are not exhausted unless an invocation was blocked.
        blocked = failure.get('resource') == key
        if used <= 0 and not blocked:
            continue
        reserve = state.get('finalization_reserve', {}).get(key, 0)
        kind = ('limit' if used >= limit else 'insufficient' if blocked
                else 'reserve' if state.get('budget_phase') == 'FINALIZING'
                and reserve > 0 and used + reserve >= limit else None)
        if kind:
            result.append({'field': key, 'label': LABELS[key], 'used': round(used, 2),
                           'limit': limit, 'kind': kind, 'reserve': min(reserve, max(0, limit - used)) if kind == 'reserve' else 0,
                           'requested': failure.get('requested', 0) if blocked else 0,
                           'unit': '秒' if key == 'duration' else 'Token' if key.endswith('_tokens') else '个' if key == 'max_collaborators' else '层' if key == 'agent_depth' else '次'})
    return result


async def restore_budget_notices(db, conv_id, messages):
    """Restore old final replies from their exact owned checkpoint, without DB writes."""
    import uuid
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import set_committed_value
    from cortexa.runtime.models import RuntimeGoal
    from cortexa.runtime.store import owned

    ids = set()
    for message in messages:
        meta = message.metadata_json or {}
        if message.role != 'assistant' or 'budget_notices' in meta:
            continue
        try:
            ids.add(uuid.UUID(str(meta.get('goal_id'))))
        except (ValueError, TypeError):
            continue
    if not ids:
        return
    rows = await db.scalars(select(RuntimeGoal).where(*owned(),
        RuntimeGoal.conversation_id == conv_id, RuntimeGoal.id.in_(ids)))
    by_message = {r.state.get('result_message_id'): r.state for r in rows}
    for message in messages:
        state = by_message.get(str(message.id))
        if state is not None and 'budget_notices' not in (message.metadata_json or {}):
            set_committed_value(message, 'metadata_json', {
                **(message.metadata_json or {}), 'budget_notices': budget_notices(state)})
