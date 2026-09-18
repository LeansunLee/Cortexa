import asyncio
import logging

from agentdevstu.agents.prompts import reference_message
from agentdevstu.memory.service import retrieve_memories, format_memories_for_prompt


async def memory_reference(agent, query, db):
    from agentdevstu.agents.retrieval import plan_retrieval
    if not plan_retrieval(query).memory:
        return None
    try:
        memories = await asyncio.wait_for(retrieve_memories(
            workspace_id=agent.workspace_id, agent_id=agent.id, query=query, db=db, top_k=5,
        ), timeout=5)
        if memories:
            return reference_message("相关记忆", format_memories_for_prompt(memories))
    except Exception:
        logging.getLogger(__name__).warning("Memory retrieval failed", exc_info=True)
    return None


async def organization_reference(agent, db):
    # Proxy context is not forwarded: external requests retain their configured payload allowlist.
    if getattr(agent, "agent_type", "llm") == "proxy":
        return []
    from agentdevstu.organization.service import organization_context
    return [reference_message("当前空间组织与真人职责", await organization_context(db, agent.workspace_id))]
