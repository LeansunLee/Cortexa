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


async def prepare_bindings(agent, query, sources, db, *, context_budget=6000, project_ids=None, conversation_id=None):
    from cortexa.api.conversations import _build_data_tools, _load_agent_capabilities

    caps = await _load_agent_capabilities(agent.id, db, query)
    # Main reasoning sees the existing tool descriptions/contracts. Deterministic
    # parameter normalization is reused; no hidden per-tool parameter LLM call.
    business = _build_data_tools(caps, sources, model=None, user_query=query, agent_id=agent.id, read_only=True)
    web = await load_search_tools(agent, db, query, sources)
    from cortexa.tools.registry import load_registry_tool_pairs
    registry_pairs = await load_registry_tool_pairs(agent, db, sources=sources)
    manifest_map = {tool.name: manifest for tool, manifest in registry_pairs}
    registry = [tool for tool, _ in registry_pairs]
    cap_map = {f"query_{item['capability'].id.hex}": item["capability"] for item in caps}
    bindings = []
    from cortexa.projects.runtime import tools as project_tools
    project = project_tools(agent.id, project_ids or [], sources)
    if conversation_id is not None:
        from cortexa.conversation import artifacts as artifacts_store
        from cortexa.security.access import actor_required
        try:
            project = [*project, *artifacts_store.save_document_tool(
                conversation_id, agent.workspace_id, actor_required().user_id, agent.id)]
        except Exception:
            pass
    from cortexa.work import runtime as work_runtime
    project = [*project, *work_runtime.tools(agent.id, sources)]
    for tool in [*business, *web, *registry, *project]:
        capability = cap_map.get(tool.name)
        manifest = manifest_map.get(tool.name)
        adapter = tool_adapter(tool, str(agent.workspace_id), capability=capability)
        if manifest is not None:
            # Registry-driven policy: manifest fields override adapter defaults.
            adapter.descriptor.risk_level = manifest.risk_level
            adapter.descriptor.requires_confirmation = manifest.requires_confirmation
            adapter.descriptor.timeout = manifest.timeout
            adapter.descriptor.input_budget = manifest.input_budget
            adapter.descriptor.availability = "available"
            adapter.descriptor.aliases = list(manifest.aliases)
            adapter.descriptor.domains = list(manifest.domains)
            adapter.descriptor.constraints["quota_per_goal"] = manifest.quota.per_goal
            if manifest.usage_rules:
                adapter.descriptor.constraints["usage_rules"] = manifest.usage_rules
        if tool.name == "project_read":
            adapter.descriptor.risk_level = "low"
            adapter.descriptor.requires_confirmation = False
            adapter.descriptor.timeout = 10
        if tool.name == "save_document":
            # Conversation-scoped write into the requester's own artifact store;
            # ownership and turn limits are enforced inside the tool itself.
            adapter.descriptor.risk_level = "low"
            adapter.descriptor.requires_confirmation = False
            adapter.descriptor.availability = "available"
            adapter.descriptor.timeout = 15
        if tool.name == "work_read":
            # Read-only work lookup; visibility is enforced by the work service
            # against the requesting user inside the tool.
            adapter.descriptor.risk_level = "low"
            adapter.descriptor.requires_confirmation = False
            adapter.descriptor.availability = "available"
            adapter.descriptor.timeout = 10
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
                elif tool.name in {"project_read", "save_document", "work_read"}:
                    if tool.name == "project_read":
                        from cortexa.projects.service import get
                        import uuid
                        for ident in project_ids or []:
                            await get(check_db, uuid.UUID(str(ident)))
                    # save_document writes only into the requester's own
                    # conversation store; work_read visibility is enforced by the
                    # work service against the requesting user.
                else:
                    fresh_web = await load_search_tools(fresh, check_db, query, sources)
                    from cortexa.tools.registry import load_registry_tools
                    fresh_registry = await load_registry_tools(fresh, check_db, sources=sources)
                    if not any(t.name == tool.name for t in [*fresh_web, *fresh_registry]):
                        raise PermissionError("capability_revoked")

        async def invoke(args, action_id, tool=tool, adapter=adapter):
            raw = await tool.ainvoke(args)
            return InvocationResult(adapter.observe(raw, action_id), str(raw), raw)

        bindings.append(Binding(tool, adapter, invoke, check_access))
    from cortexa.conversation.questions import ask_user_tool, question
    from cortexa.runtime.observations import Observation
    tool = ask_user_tool()
    adapter = tool_adapter(tool, str(agent.workspace_id))
    adapter.descriptor.type = CapabilityType.TOOL
    adapter.descriptor.risk_level = 'low'
    adapter.descriptor.requires_confirmation = False
    adapter.descriptor.availability = 'available'
    async def ask(args, action_id, adapter=adapter):
        public = question(args, agent)
        return InvocationResult(Observation('TOOL', adapter.descriptor.id, action_id, 'NOT_READY',
            summary=public['question'], metadata={'user_question':public}), public['question'], {})
    bindings.append(Binding(tool, adapter, ask))
    from cortexa.tools.skills import build_skill_index, make_load_skill_tool
    skill_index = await build_skill_index(agent, db)
    if skill_index:
        tool = make_load_skill_tool(agent)
        adapter = tool_adapter(tool, str(agent.workspace_id))
        adapter.descriptor.type = CapabilityType.TOOL
        adapter.descriptor.risk_level = 'low'
        adapter.descriptor.requires_confirmation = False
        adapter.descriptor.availability = 'available'
        adapter.descriptor.timeout = 5
        async def load_skill(args, action_id, tool=tool, adapter=adapter):
            raw = await tool.ainvoke(args)
            return InvocationResult(adapter.observe(raw, action_id), str(raw), raw)
        # 每轮授权在 load_skill_body 内部以全新会话复查（绑定/启用/同名）。
        async def skill_access(tool=tool):
            async with async_session_factory() as check_db:
                await require_agent_use(check_db, agent.id)
        bindings.append(Binding(tool, adapter, load_skill, skill_access))
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
                    raw = await retrieve_knowledge(fresh, args["query"], retrieval_db, sources=evidence, stats=stats, context_budget=context_budget)
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
            description="检索当前 Agent 已授权的内部知识与来源。只有 DIRECT 支持其覆盖的目标事实；RELATED/BACKGROUND 仅用于标注用途的参考。Evidence Insufficient 时如实说明不足，不得把参考资料或未分级历史来源包装为真实案例。"
            if kind == CapabilityType.KNOWLEDGE
            else "检索当前 Agent 历史记忆，记忆仅作参考",
            args_schema=RetrievalInput,
        )
        bindings.append(Binding(tool, adapter, retrieve,
                                cache_scope={"knowledge_relevance": "entity_evidence_v1"} if kind == CapabilityType.KNOWLEDGE else None))
    return bindings, business
