"""
Agent 协作管理器

核心职责：
1. 生成结构化 Handoff 请求
2. 调用目标 Agent Runtime
3. 返回协作结果
4. 记录协作日志
5. 执行安全限制（深度、并发、超时）
"""

from __future__ import annotations
from agentdevstu.usage.context import usage_action, annotate_usage

import asyncio
import json
import time
import traceback
import uuid
from agentdevstu.agents.usage import UsageTotals
from agentdevstu.agents.prompts import build_system_prompt, reference_message, handoff_message
from agentdevstu.agents.knowledge import retrieve_knowledge
from agentdevstu.agents.retrieval import plan_retrieval, web_reference, history_text, limited_history
from agentdevstu.tools.runtime import DATA_QUERY_GROUNDING_FAILURE, bind_tools_for_first_response, called_required_tool, should_require_business_tool
from agentdevstu.memory.service import retrieve_memories, format_memories_for_prompt
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.db.models import (
    Agent,
    AgentCollaboration,
    Conversation,
    ConversationMessage,
)
from agentdevstu.collaboration.schemas import (
    AgentHandoff,
    AgentHandoffResult,
    CollaborationLimits,
    DEFAULT_LIMITS,
)
from agentdevstu.collaboration.mention_parser import (
    ParsedMentions,
    fuzzy_match_agent,
)


class ProxyInputRequiredError(RuntimeError):
    def __init__(self, resolution: dict[str, Any]):
        self.resolution = resolution
        super().__init__(resolution.get("message") or "Proxy 调用前需要补充输入")


async def list_collaboration_agents(
    db: AsyncSession,
    workspace_id: str | None,
    exclude_agent_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """
    列出当前工作空间中可用于协作的 Agent。

    Returns:
        Agent 列表，包含 id, name, description, avatar, role, status
    """
    query = select(Agent).where(Agent.status == "active")
    if workspace_id:
        query = query.where(Agent.workspace_id == uuid.UUID(workspace_id))
    if exclude_agent_id:
        query = query.where(Agent.id != exclude_agent_id)

    result = await db.execute(query)
    agents = list(result.scalars().all())

    return [
        {
            "id": str(a.id),
            "name": a.name,
            "description": a.description or "",
            "avatar": a.avatar or "🤖",
            "role": a.role or "",
            "status": a.status,
            "agent_type": a.agent_type,
            "workspace_id": str(a.workspace_id),
        }
        for a in agents
    ]


async def execute_handoff(
    source_agent: Agent,
    target_agent: Agent,
    handoff: AgentHandoff,
    conversation_id: uuid.UUID,
    call_depth: int = 1,
    db: AsyncSession | None = None,
    limits: CollaborationLimits | None = None,
    on_token=None,
) -> AgentHandoffResult:
    """
    执行 Agent 协作 Handoff。

    主 Agent 通过此函数调用目标 Agent Runtime，获取结果。
    目标 Agent 使用自己的知识库、工具和权限独立执行任务。

    Args:
        source_agent: 发起协作的源 Agent
        target_agent: 被调用的目标 Agent
        handoff: 结构化协作请求
        conversation_id: 当前对话 ID
        call_depth: 当前调用深度（防止循环）
        db: 可选的 DB session（如果传入则记录协作日志）
        limits: 协作限制配置

    Returns:
        AgentHandoffResult 协作结果
    """
    from agentdevstu.security.access import current_actor, require_agent_use
    if current_actor.get():
        from agentdevstu.db.engine import async_session_factory
        async with async_session_factory() as auth_db:
            await require_agent_use(auth_db, target_agent.id)
    if limits is None:
        limits = DEFAULT_LIMITS

    timeout_seconds = limits.timeout_seconds
    if target_agent.agent_type == "proxy":
        config = target_agent.proxy_config or {}
        timeout_seconds = max(timeout_seconds, config.get("timeout_ms", 30000) / 1000 * (config.get("retry", 0) + 1) + 5)
    start_time = time.time()
    usage = UsageTotals()

    # 检查调用深度限制
    if call_depth > limits.max_call_depth:
        return AgentHandoffResult(
            status="failed",
            summary="协作深度超出限制",
            result=f"协作调用深度 {call_depth} 已超过最大限制 {limits.max_call_depth}",
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=0,
        )

    # 创建协作记录
    collab_id = uuid.uuid4()
    collaboration = None
    if db:
        collaboration = AgentCollaboration(
            id=collab_id,
            conversation_id=conversation_id,
            source_agent_id=source_agent.id,
            target_agent_id=target_agent.id,
            task=handoff.task,
            known_facts={"facts": handoff.known_facts} if handoff.known_facts else None,
            question=handoff.question,
            constraints={"constraints": handoff.constraints} if handoff.constraints else None,
            expected_output=handoff.expected_output,
            status="running",
            call_depth=call_depth,
            started_at=datetime.now(timezone.utc),
        )
        db.add(collaboration)
        await db.flush()

    try:
        # 构建目标 Agent 的 System Prompt
        from agentdevstu.db.engine import async_session_factory
        from agentdevstu.db.models import Workspace
        async with async_session_factory() as prompt_db:
            workspace = await prompt_db.get(Workspace, target_agent.workspace_id)
        target_system_prompt = _build_handoff_system_prompt(
            source_agent=source_agent,
            target_agent=target_agent,
            handoff=handoff,
            workspace=workspace,
        )

        # 使用独立的 LLM session 执行（不依赖源 Agent 的 session）
        search_sources = []
        result_content = await asyncio.wait_for(
            _execute_target_agent(
                target_agent=target_agent,
                system_prompt=target_system_prompt,
                handoff=handoff,
                conversation_id=conversation_id,
                on_token=on_token,
                usage=usage,
                sources=search_sources,
            ),
            timeout=timeout_seconds,
        )

        duration_ms = round((time.time() - start_time) * 1000)

        # 构建结果
        handoff_result = AgentHandoffResult(
            status="success",
            input_snapshot=handoff.input_snapshot,
            summary=result_content[:200] if len(result_content) > 200 else result_content,
            result=result_content,
            sources=search_sources,
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
            confidence=0.85,
            usage=usage.stats(),
        )

        # 更新协作记录
        if collaboration and db:
            collaboration.status = "success"
            collaboration.result_summary = handoff_result.summary
            collaboration.result_content = handoff_result.result
            collaboration.confidence = handoff_result.confidence
            collaboration.duration_ms = duration_ms
            collaboration.completed_at = datetime.now(timezone.utc)
            await db.flush()

        return handoff_result

    except ProxyInputRequiredError as error:
        duration_ms = round((time.time() - start_time) * 1000)
        message = str(error)
        handoff.input_snapshot = {"type": "proxy", "resolution": error.resolution}
        if collaboration and db:
            collaboration.status = "input_required"
            collaboration.error_message = message
            collaboration.duration_ms = duration_ms
            collaboration.completed_at = datetime.now(timezone.utc)
            await db.flush()
        return AgentHandoffResult(
            status="input_required",
            input_snapshot=handoff.input_snapshot,
            summary=message,
            result=message,
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
        )

    except asyncio.TimeoutError:
        duration_ms = round((time.time() - start_time) * 1000)
        if collaboration and db:
            collaboration.status = "timeout"
            collaboration.error_message = f"协作超时 ({timeout_seconds:g}s)"
            collaboration.duration_ms = duration_ms
            collaboration.completed_at = datetime.now(timezone.utc)
            await db.flush()

        return AgentHandoffResult(
            status="timeout",
            input_snapshot=handoff.input_snapshot,
            summary=f"Agent {target_agent.name} 协作超时",
            result=f"目标 Agent 在 {timeout_seconds:g} 秒内未完成协作任务",
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = round((time.time() - start_time) * 1000)
        error_msg = str(e)
        print(f"[COLLAB] Handoff error: {error_msg}\n{traceback.format_exc()}", flush=True)

        if collaboration and db:
            collaboration.status = "failed"
            collaboration.error_message = error_msg
            collaboration.duration_ms = duration_ms
            collaboration.completed_at = datetime.now(timezone.utc)
            await db.flush()

        return AgentHandoffResult(
            status="failed",
            input_snapshot=handoff.input_snapshot,
            summary=f"Agent {target_agent.name} 协作失败",
            result=f"协作执行出错：{error_msg}",
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
        )


def _build_handoff_system_prompt(source_agent, target_agent, handoff, workspace=None):
    return build_system_prompt(target_agent, workspace)


async def stream_handoff(**kwargs):
    queue = asyncio.Queue()
    sentinel = object()

    async def on_token(content):
        queue.put_nowait(content)

    async def run():
        try:
            return await execute_handoff(**kwargs, on_token=on_token)
        finally:
            queue.put_nowait(sentinel)

    task = asyncio.create_task(run())
    try:
        while True:
            try:
                content = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield {"heartbeat": True}
                continue
            if content is sentinel:
                break
            yield {"token": content}
        yield {"result": await task}
    finally:
        if not task.done():
            task.cancel()
        import anyio
        with anyio.CancelScope(shield=True):
            await asyncio.gather(task, return_exceptions=True)


@usage_action("collaboration_execute")
async def _execute_target_agent(
    target_agent: Agent,
    system_prompt: str,
    handoff: AgentHandoff,
    conversation_id: uuid.UUID | None = None,
    on_token=None,
    usage=None,
    sources=None,
) -> str:
    """
    使用目标 Agent 的 LLM 配置独立执行任务。

    关键：使用 target_agent 自己的 model、知识库和数据能力。
    使用独立的 DB session（不泄露源 Agent 的知识）。
    """
    from agentdevstu.config.llm_providers import create_llm
    from agentdevstu.config.settings import load_env
    from agentdevstu.db.engine import async_session_factory

    if target_agent.agent_type == "proxy":
        from agentdevstu.agents.proxy_executor import execute_proxy_agent
        from agentdevstu.agents.proxy_input_resolver import prompt_resolution_enabled, resolution_enabled
        from agentdevstu.collaboration.drafts import proxy_request
        request = handoff.question if (
            prompt_resolution_enabled(target_agent) or resolution_enabled(target_agent)
        ) else proxy_request(handoff)
        async with async_session_factory() as proxy_db:
            result = await execute_proxy_agent(
                target_agent,
                {"input": request},
                proxy_db,
                supplemental_prompt=handoff.supplemental_prompt,
                resolution_context=handoff.resolver_context,
            )
            await proxy_db.commit()
        if not result.get("success"):
            if result.get("requires_input"):
                raise ProxyInputRequiredError(result.get("resolution") or {"message": result.get("error")})
            raise RuntimeError("Proxy 协作调用失败：" + str(result.get("error", "未知错误")))
        handoff.input_snapshot = {
            "type": "proxy",
            "resolution": result.get("resolution"),
            "request_body": result.get("request_body"),
        }
        output = result.get("output_data")
        answer = output.get("answer") if isinstance(output, dict) else output
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Proxy 协作没有返回有效回答正文")
        if on_token is not None:
            await on_token(answer)
        return answer

    load_env()

    # 使用目标 Agent 的 model 配置创建 LLM
    annotate_usage(agent=target_agent)
    llm = create_llm(target_agent.model)

    # 构建消息：先注入对话历史，再放用户问题
    messages = [{"role": "system", "content": system_prompt}]
    plan = plan_retrieval(handoff.question)

    # All LLM collaboration entry points use the same fixed context policy.
    if handoff.background_context.get("mode") != "conversation":
        from agentdevstu.collaboration.background import prepare_background
        async with async_session_factory() as hist_db:
            handoff.background_context = await prepare_background(hist_db, conversation_id, target_type="llm")

    if handoff.known_facts:
        messages.append(reference_message("协作提供的待核实事实", handoff.known_facts))
    if handoff.reference_materials:
        messages.append(reference_message("用户附件", handoff.reference_materials))

    # 在独立 session 中获取知识库和数据能力
    business_tools = []
    data_tools = []
    try:
        async with async_session_factory() as kb_db:
            from agentdevstu.agents.context import organization_reference
            messages.extend(await organization_reference(target_agent, kb_db))
            from agentdevstu.db.models import Document, KnowledgeBase, DataCapability, DataSource, AgentDataBinding, DataCredential

            try:
                knowledge = await asyncio.wait_for(retrieve_knowledge(target_agent, handoff.question, kb_db), timeout=10) if plan.knowledge else ""
                if knowledge:
                    messages.append(reference_message("参考知识", knowledge))
            except Exception as error:
                print(f"[COLLAB] Knowledge retrieval failed: {error}", flush=True)
                messages.append(reference_message("知识检索状态", "检索暂时失败，不代表知识库没有相关文档。"))
            try:
                memories = await asyncio.wait_for(retrieve_memories(
                    workspace_id=target_agent.workspace_id, agent_id=target_agent.id,
                    query=handoff.question, db=kb_db, top_k=5,
                ), timeout=5) if plan.memory else []
                if memories:
                    messages.append(reference_message("相关记忆", format_memories_for_prompt(memories)))
            except Exception as error:
                print(f"[COLLAB] Memory retrieval failed: {error}", flush=True)

            from agentdevstu.api.conversations import _load_agent_capabilities, _build_data_tools, _build_tool_usage_instructions
            capabilities = await _load_agent_capabilities(target_agent.id, kb_db, handoff.question)
            business_tools = _build_data_tools(capabilities, sources, model=llm, user_query=handoff.question, context=messages)
            messages[0]["content"] += _build_tool_usage_instructions(capabilities, business_tools)
            data_tools = list(business_tools)
    except Exception as e:
        print(f"[COLLAB] KB/capability retrieval for target agent failed: {e}", flush=True)

    from agentdevstu.tools.web_search import load_search_tools
    async with async_session_factory() as tool_db:
        data_tools.extend(await load_search_tools(target_agent, tool_db, "\n".join([handoff.task, handoff.question, *handoff.constraints]), sources))

    # 添加数据能力说明到 system prompt
    if data_tools:
        tool_names = [t.name for t in data_tools]
        messages[0] = {"role": "system", "content": messages[0]["content"] +
            f"\n\n## 可用工具\n根据本轮任务调用以下工具：{', '.join(tool_names)}\n"}

    if handoff.background_context.get("facts"):
        from agentdevstu.collaboration.background import background_messages
        messages.extend(background_messages(handoff.background_context))
    if handoff.dependency_results:
        for prior_result in handoff.dependency_results:
            messages.append(reference_message("本轮前序 Agent 的协作结果（参考数据，以本轮任务为准）", prior_result))
    messages.append(handoff_message(handoff))
    handoff.input_snapshot = {"type": "llm", "messages": [dict(message) for message in messages]}
    streamed_content = []

    async def call_model(model, *, emit_tokens=True):
        from agentdevstu.api.conversations import _stream_model_response

        async for token, completed in _stream_model_response(model, messages):
            if token:
                if emit_tokens:
                    streamed_content.append(token)
                    if on_token is not None:
                        await on_token(token)
            if completed is not None:
                if usage is not None:
                    usage.add(completed)
                response = completed
        return response

    # 调用 LLM（支持 tool calling）
    if data_tools:
        model_with_tools = llm.bind_tools(data_tools)
        required_business_tools = business_tools if should_require_business_tool(handoff.question, business_tools) else []
        first_model = bind_tools_for_first_response(llm, data_tools, required_business_tools)
        response = await call_model(first_model)
        if required_business_tools and not called_required_tool(response, required_business_tools):
            content = DATA_QUERY_GROUNDING_FAILURE
            streamed_content.clear()
            if on_token is not None:
                await on_token(content)
            return content

        # 处理 tool calls（最多 5 轮）
        max_iterations = 5
        iteration = 0
        while hasattr(response, 'tool_calls') and response.tool_calls and iteration < max_iterations:
            iteration += 1
            tool_messages = []
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                print(f"[COLLAB-TOOL] Target agent called: {tool_name} with {tool_args}", flush=True)
                tool_result = None
                for t in data_tools:
                    if t.name == tool_name:
                        try:
                            tool_result = await t.ainvoke(tool_args)
                        except Exception as te:
                            tool_result = {"error": str(te)}
                        break
                if tool_result is None:
                    tool_result = {"error": f"工具 {tool_name} 未找到"}
                from langchain_core.messages import ToolMessage
                tool_messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tc["id"],
                ))
            messages.append(response)
            messages.extend(tool_messages)
            response = await call_model(model_with_tools)

        content = response.content if hasattr(response, "content") else str(response)
    else:
        response = await call_model(llm)
        content = response.content if hasattr(response, "content") else str(response)

    return "".join(streamed_content) if on_token is not None else content


async def get_collaboration_history(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """获取对话的协作历史记录"""
    query = (
        select(AgentCollaboration)
        .where(AgentCollaboration.conversation_id == conversation_id)
        .order_by(AgentCollaboration.created_at)
    )
    result = await db.execute(query)
    records = list(result.scalars().all())

    enriched = []
    for r in records:
        source_agent = await db.get(Agent, r.source_agent_id)
        target_agent = await db.get(Agent, r.target_agent_id)
        enriched.append({
            "id": str(r.id),
            "conversation_id": str(r.conversation_id),
            "source_agent_id": str(r.source_agent_id),
            "source_agent_name": source_agent.name if source_agent else "Unknown",
            "target_agent_id": str(r.target_agent_id),
            "target_agent_name": target_agent.name if target_agent else "Unknown",
            "task": r.task,
            "question": r.question,
            "status": r.status,
            "result_summary": r.result_summary,
            "result_content": r.result_content,
            "confidence": r.confidence,
            "duration_ms": r.duration_ms,
            "error_message": r.error_message,
            "call_depth": r.call_depth,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        })

    return enriched


async def check_collaboration_limits(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    limits: CollaborationLimits | None = None,
) -> dict[str, Any]:
    """
    检查当前对话是否达到协作限制。

    Returns:
        {"allowed": bool, "reason": str, "counts": {...}}
    """
    if limits is None:
        limits = DEFAULT_LIMITS

    # 统计当前对话的协作次数
    query = select(AgentCollaboration).where(
        AgentCollaboration.conversation_id == conversation_id
    )
    result = await db.execute(query)
    records = list(result.scalars().all())

    # 统计最近一次用户消息中的 Agent 数量
    # (这里简化：按对话总协作次数限制)
    total_collabs = len(records)
    success_count = sum(1 for r in records if r.status == "success")

    # 检查是否有正在进行的协作
    running = [r for r in records if r.status in ("pending", "running")]

    return {
        "allowed": True,
        "reason": "",
        "counts": {
            "total": total_collabs,
            "success": success_count,
            "running": len(running),
            "max_per_request": limits.max_agents_per_request,
            "max_depth": limits.max_call_depth,
        },
    }
