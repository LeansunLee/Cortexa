"""Execute persisted tasks and sequential workflows using published Agents."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.agents import _build_system_prompt
from cortexa.config.llm_providers import create_llm
from cortexa.db.models import AgentRun, AgentVersion, Task, TaskRun, WorkflowEdge, WorkflowNode
from cortexa.security.access import actor_required, require_agent_use
from cortexa.usage.context import annotate_usage, usage_action


def ordered_nodes(nodes: list[WorkflowNode], edges: list[WorkflowEdge]) -> list[WorkflowNode]:
    """Validate and order the currently supported single-path Agent workflow."""
    by_id = {node.id: node for node in nodes}
    if not by_id or any(node.type != "agent" or not node.agent_id for node in nodes):
        raise ValueError("工作流至少需要一个已绑定 Agent 的步骤")
    outgoing: dict[uuid.UUID, list[uuid.UUID]] = {node_id: [] for node_id in by_id}
    incoming = {node_id: 0 for node_id in by_id}
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for edge in edges:
        pair = (edge.source_node_id, edge.target_node_id)
        if pair[0] not in by_id or pair[1] not in by_id or pair[0] == pair[1] or pair in seen:
            raise ValueError("工作流连接无效或重复")
        seen.add(pair)
        outgoing[pair[0]].append(pair[1])
        incoming[pair[1]] += 1
    if len(nodes) > 1 and len(edges) != len(nodes) - 1:
        raise ValueError("请将所有步骤按执行顺序连接")
    ready = [node_id for node_id, count in incoming.items() if count == 0]
    root_count = len(ready)
    result = []
    while ready:
        node_id = ready.pop(0)
        result.append(by_id[node_id])
        for target in outgoing[node_id]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if len(result) != len(nodes) or root_count != 1:
        raise ValueError("工作流步骤必须组成一条无循环的执行路径")
    if any(len(targets) > 1 for targets in outgoing.values()) or any(sum(edge.target_node_id == node_id for edge in edges) > 1 for node_id in by_id):
        raise ValueError("当前仅支持顺序连接的工作流")
    return result


@usage_action("workflow_execute", source="workflow")
async def run_task(db: AsyncSession, task: Task, steps: list[tuple[str, uuid.UUID]], workflow_id: uuid.UUID | None = None) -> TaskRun:
    """Persist real model results and explicit failures; never fabricate a success."""
    actor = actor_required()
    task.status = "running"
    run = TaskRun(
        task_id=task.id,
        workflow_id=workflow_id,
        owner_user_id=actor.user_id,
        status="running",
        input_data=dict(task.input_data or {}),
        output_data={},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    context: dict = {"input": dict(task.input_data or {}), "steps": {}}
    current_agent_run_id = None
    try:
        for step_name, agent_id in steps:
            agent = await require_agent_use(db, agent_id)
            version = await db.scalar(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent.id, AgentVersion.is_published.is_(True))
                .order_by(AgentVersion.version_number.desc())
                .limit(1)
            )
            if not version:
                raise ValueError(f"步骤 {step_name} 的 Agent 尚无已发布版本")
            agent_run = AgentRun(
                agent_id=agent.id,
                agent_version_id=version.id,
                owner_user_id=actor.user_id,
                input_data=context.copy(),
                status="running",
            )
            db.add(agent_run)
            await db.commit()
            await db.refresh(agent_run)
            current_agent_run_id = agent_run.id
            annotate_usage(agent_id=agent.id, agent_name=agent.name)
            prompt = f"任务：{task.name}\n{task.description or ''}\n当前输入与已完成步骤：\n{json.dumps(context, ensure_ascii=False, default=str)}"
            response = await asyncio.wait_for(
                create_llm(agent.model).ainvoke(
                    [SystemMessage(content=_build_system_prompt(agent)), HumanMessage(content=prompt)]
                ),
                timeout=120,
            )
            output = response.content if isinstance(response.content, str) else str(response.content)
            agent_run.output_data = {"result": output}
            agent_run.status = "completed"
            agent_run.completed_at = datetime.now(timezone.utc)
            agent_run.duration_ms = int((agent_run.completed_at - agent_run.created_at).total_seconds() * 1000)
            context["steps"][step_name] = output
            run.output_data = dict(context)
            await db.commit()
            current_agent_run_id = None
        run.status = task.status = "completed"
        task.output_data = dict(context)
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as error:
        await db.rollback()
        task = await db.get(Task, task.id)
        run = await db.get(TaskRun, run.id)
        message = f"运行失败：{type(error).__name__}"
        if current_agent_run_id:
            agent_run = await db.get(AgentRun, current_agent_run_id)
            if agent_run:
                agent_run.status = "failed"
                agent_run.error_message = message
                agent_run.completed_at = datetime.now(timezone.utc)
        task.status = run.status = "failed"
        run.error_message = message
        run.output_data = dict(context)
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
    await db.refresh(run)
    return run
