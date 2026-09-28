"""Delegate to mature retrieval/data/web executors under the Goal boundary."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from cortexa.agents.knowledge import retrieve_knowledge
from cortexa.agents.retrieval import plan_retrieval
from cortexa.db.engine import async_session_factory
from cortexa.db.models import AgentDataBinding, DataCapability
from cortexa.memory.service import format_memories_for_prompt, retrieve_memories
from cortexa.runtime.adapters import retrieval_adapter, tool_adapter
from cortexa.runtime.capabilities import CapabilityType
from cortexa.runtime.loop import Binding, InvocationResult
from cortexa.security.access import require_agent_use
from cortexa.tools.web_search import load_search_tools


class RetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)


async def prepare_bindings(agent, query, sources, db):
    from cortexa.api.conversations import _build_data_tools, _load_agent_capabilities

    caps = await _load_agent_capabilities(agent.id, db, query)
    # Main reasoning sees the existing tool descriptions/contracts. Deterministic
    # parameter normalization is reused; no hidden per-tool parameter LLM call.
    business = _build_data_tools(caps, sources, model=None, user_query=query, agent_id=agent.id, read_only=True)
    web = await load_search_tools(agent, db, query, sources)
    cap_map = {f"query_{item['capability'].id.hex}": item["capability"] for item in caps}
    bindings = []
    for tool in [*business, *web]:
        capability = cap_map.get(tool.name)
        adapter = tool_adapter(tool, str(agent.workspace_id), capability=capability)
        if capability is not None:
            from cortexa.data.sql_drafts import validate_sql

            try:
                validate_sql(capability.query_template or "")
                adapter.descriptor.risk_level = "low"
                adapter.descriptor.requires_confirmation = False
                adapter.descriptor.constraints["read_only_transaction"] = True
            except ValueError:
                adapter.descriptor.risk_level = "high"

        async def check_access(tool=tool, capability=capability):
            # Revalidate each selected capability, including cache-independent DB grants.
            async with async_session_factory() as check_db:
                fresh = await require_agent_use(check_db, agent.id)
                if capability is not None:
                    granted = await check_db.scalar(
                        select(DataCapability.id)
                        .join(AgentDataBinding, AgentDataBinding.data_capability_id == DataCapability.id)
                        .where(
                            AgentDataBinding.agent_id == fresh.id,
                            DataCapability.id == capability.id,
                            DataCapability.workspace_id == fresh.workspace_id,
                            DataCapability.status == "active",
                        )
                    )
                    if granted is None:
                        raise PermissionError("capability_revoked")
                else:
                    fresh_web = await load_search_tools(fresh, check_db, query, sources)
                    if not any(t.name == tool.name for t in fresh_web):
                        raise PermissionError("capability_revoked")

        async def invoke(args, action_id, tool=tool, adapter=adapter):
            raw = await tool.ainvoke(args)
            return InvocationResult(adapter.observe(raw, action_id), str(raw), raw)

        bindings.append(Binding(tool, adapter, invoke, check_access))
    plan = plan_retrieval(query)
    for kind in (CapabilityType.KNOWLEDGE, CapabilityType.MEMORY):
        if not getattr(plan, kind.lower()):
            continue
        adapter = retrieval_adapter(agent, kind)

        async def retrieve(args, action_id, adapter=adapter, kind=kind):
            async with async_session_factory() as retrieval_db:
                fresh = await require_agent_use(retrieval_db, agent.id)
                if kind == CapabilityType.KNOWLEDGE:
                    evidence, stats = [], {}
                    raw = await retrieve_knowledge(fresh, args["query"], retrieval_db, sources=evidence, stats=stats)
                    sources.extend(evidence)
                    return InvocationResult(
                        adapter.observe(raw, action_id, evidence=evidence, metadata=stats), raw, raw
                    )
                memories = await retrieve_memories(
                    workspace_id=fresh.workspace_id, agent_id=fresh.id, query=args["query"], db=retrieval_db, top_k=5
                )
                text = format_memories_for_prompt(memories)
                observation = adapter.observe(memories, action_id)
                # Persist the actual material given to the model with its provenance;
                # ORM entities and internal embeddings never enter JSON serialization.
                return InvocationResult(observation, text, {"text": text, "provenance": observation.evidence})

        # LangChain sees schema/description only; execution goes through the binding.
        async def placeholder(query: str):
            raise RuntimeError("Use Goal capability executor")

        tool = StructuredTool.from_function(
            coroutine=placeholder,
            name=kind.lower() + "_retrieve",
            description="检索当前 Agent 已授权的内部知识与来源"
            if kind == CapabilityType.KNOWLEDGE
            else "检索当前 Agent 历史记忆，记忆仅作参考",
            args_schema=RetrievalInput,
        )
        bindings.append(Binding(tool, adapter, retrieve))
    return bindings, business
