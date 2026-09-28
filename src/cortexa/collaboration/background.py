"""Fixed collaboration context policy: Proxy gets no context; LLM gets recent context."""
from sqlalchemy import select
from cortexa.db.models import ConversationMessage


async def prepare_proxy_resolution_context(db, conversation_id, *, exclude_message_id=None, attachments=None):
    """Collect bounded local-only context for the Proxy input resolver."""
    from cortexa.agents.retrieval import history_text

    query = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
    if exclude_message_id:
        query = query.where(ConversationMessage.id != exclude_message_id)
    rows = (
        (await db.execute(query.order_by(ConversationMessage.created_at.desc()).limit(12))).scalars().all()
        if conversation_id else []
    )
    context = [
        {"role": message.role, "content": history_text(message.content)[:3000]}
        for message in reversed(rows)
        if message.role in ("user", "assistant") and history_text(message.content)
    ]
    context.extend(
        {"role": "attachment", "content": str(content)[:3000]}
        for content in (attachments or [])[:3]
        if content
    )
    return context


async def prepare_background(db, conversation_id, draft=None, main_input='', model_name=None, *, target_type, prior_results=None, attachments=None, exclude_message_id=None, usage=None):
    # Decide using the persisted target type, never a client-supplied mode.
    if target_type == 'proxy':
        return {'mode': 'none', 'status': 'ready', 'facts': [], 'dependency_ids': [],
                'reason': 'Proxy Agent 仅接收本轮任务，不携带对话上下文'}
    from cortexa.agents.retrieval import history_text
    query = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
    if exclude_message_id:
        query = query.where(ConversationMessage.id != exclude_message_id)
    rows = (await db.execute(query.order_by(ConversationMessage.created_at.desc()).limit(12))).scalars().all() if conversation_id else []
    facts, budget = [], 14000
    for message in rows:
        if message.role not in ('user', 'assistant') or budget <= 0:
            continue
        content = history_text(message.content)
        value = content[:min(3000, budget)]
        if not value:
            continue
        facts.append({'source': f'{message.role}:{message.id}', 'quote': value,
                      'truncated': len(value) < len(content)})
        budget -= len(value)
    facts.reverse()
    if main_input:
        facts.append({'source': '当前主输入', 'quote': main_input[:10000], 'truncated': len(main_input) > 10000})
    for index, content in enumerate((attachments or [])[:3]):
        facts.append({'source': f'附件:{index + 1}', 'quote': content[:3000], 'truncated': len(content) > 3000})
    return {'mode': 'conversation', 'status': 'ready', 'facts': facts, 'dependency_ids': [],
            'reason': 'LLM Agent 自动携带最近对话作为参考，具体工作以本轮任务为准' if facts else '当前暂无对话上下文，按本轮任务执行'}


def background_messages(background):
    from cortexa.agents.prompts import reference_message
    # Keep each source below the reference-message budget so recent input is not
    # silently dropped behind a long history block.
    return [reference_message("主对话上下文（仅供参考，以本轮协作任务为准）", fact)
            for fact in background.get('facts', [])]
