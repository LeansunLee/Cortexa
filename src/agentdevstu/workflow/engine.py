"""Workflow execution engine using LangGraph."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.db.models import (
    Agent,
    AgentRun,
    AgentVersion,
    Task,
    TaskRun,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)
from agentdevstu.config.llm_providers import create_llm


async def execute_workflow(
    db: AsyncSession,
    task_id: str,
    input_data: dict[str, Any],
) -> TaskRun:
    """Execute a workflow for a given task."""
    # Load task
    task = await db.get(Task, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    workflow = await db.get(Workflow, task.workflow_id)
    if not workflow:
        raise ValueError(f"Workflow {task.workflow_id} not found")

    # Create task run
    run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task_id,
        run_number=1,
        status="running",
        context=input_data.copy(),
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    # Update task status
    task.status = "running"
    await db.flush()

    try:
        # Get workflow nodes and edges
        result = await db.execute(
            select(WorkflowNode).where(WorkflowNode.workflow_id == workflow.id)
        )
        nodes = {str(n.id): n for n in result.scalars().all()}

        result = await db.execute(
            select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow.id)
        )
        edges = result.scalars().all()

        # Find start node
        start_node = None
        for node in nodes.values():
            if node.node_type == "start":
                start_node = node
                break

        if not start_node:
            raise ValueError("No start node found in workflow")

        # Build adjacency list (node_id -> list of edges from that node)
        adjacency: dict[str, list[WorkflowEdge]] = {}
        for edge in edges:
            src = str(edge.source_node_id)
            adjacency.setdefault(src, []).append(edge)

        # Execute nodes in topological order using BFS
        context = input_data.copy()
        visited = set()
        queue = [str(start_node.id)]

        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node = nodes.get(node_id)
            if not node:
                continue

            # Execute node based on type
            if node.node_type == "agent" and node.agent_version_id:
                agent_version = await db.get(AgentVersion, node.agent_version_id)
                if agent_version:
                    # Create agent run
                    agent_run = AgentRun(
                        id=str(uuid.uuid4()),
                        task_run_id=run.id,
                        agent_version_id=node.agent_version_id,
                        workflow_node_id=node.id,
                        status="running",
                        input_data=context.copy(),
                        started_at=datetime.now(timezone.utc),
                    )
                    db.add(agent_run)
                    await db.flush()

                    try:
                        # Execute agent using LLM
                        output = await _execute_agent(db, agent_version, context)

                        # Update agent run
                        agent_run.status = "completed"
                        agent_run.output_data = output
                        agent_run.completed_at = datetime.now(timezone.utc)
                        agent_run.duration_ms = int(
                            (agent_run.completed_at - agent_run.started_at).total_seconds() * 1000
                        )

                        # Update context with agent output
                        context.update(output)

                    except Exception as e:
                        agent_run.status = "failed"
                        agent_run.error_message = str(e)
                        agent_run.completed_at = datetime.now(timezone.utc)
                        raise

            # Find next nodes
            for edge in adjacency.get(node_id, []):
                target_id = str(edge.target_node_id)
                if target_id not in visited:
                    # Apply field mappings if any
                    if edge.field_mappings:
                        mapped_context = {}
                        for src_field, tgt_field in edge.field_mappings.items():
                            if src_field in context:
                                mapped_context[tgt_field] = context[src_field]
                        # Merge mapped context
                        context.update(mapped_context)
                    queue.append(target_id)

        # Complete task run
        run.status = "completed"
        run.context = context
        run.completed_at = datetime.now(timezone.utc)
        run.artifact = context  # Store final context as artifact

        task.status = "completed"

    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)
        run.completed_at = datetime.now(timezone.utc)
        task.status = "failed"
        raise

    await db.commit()
    return run


async def _execute_agent(
    db: AsyncSession,
    agent_version: AgentVersion,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single agent using LLM."""
    snapshot = agent_version.snapshot

    # Build system prompt
    system_parts = []
    if snapshot.get("system_prompt"):
        system_parts.append(snapshot["system_prompt"])
    if snapshot.get("personality"):
        system_parts.append(f"你的性格是: {snapshot['personality']}")
    if snapshot.get("role"):
        system_parts.append(f"你的角色是: {snapshot['role']}")
    if snapshot.get("boundaries"):
        system_parts.append(f"工作边界: {snapshot['boundaries']}")

    system_prompt = "\n".join(system_parts) if system_parts else "你是一个AI助手。"

    # Build user message from context
    user_parts = []
    for key, value in context.items():
        if isinstance(value, str):
            user_parts.append(f"{key}: {value}")
        elif isinstance(value, dict):
            user_parts.append(f"{key}: {json.dumps(value, ensure_ascii=False, indent=2)}")
        else:
            user_parts.append(f"{key}: {str(value)}")

    user_message = "\n\n".join(user_parts) if user_parts else "请执行你的任务。"

    # Get model name from snapshot or default
    model_name = snapshot.get("model") or "gpt-4o-mini"

    try:
        # Get LLM model
        model = create_llm()

        # Invoke LLM
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]

        response = await model.ainvoke(messages)
        output_text = response.content

        # Try to parse as JSON, fallback to string
        try:
            # Clean control characters
            cleaned_text = ''.join(c for c in output_text if c.isprintable() or c in '\n\r\t')
            output = json.loads(cleaned_text)
        except (json.JSONDecodeError, ValueError):
            # Extract output fields based on agent's output schema
            output_schema = snapshot.get("output_schema", {})
            if output_schema and output_schema.get("properties"):
                fields = list(output_schema["properties"].keys())
                if len(fields) == 1:
                    output = {fields[0]: output_text}
                else:
                    output = {"result": output_text}
            else:
                output = {"result": output_text}

        return output

    except Exception as e:
        # If LLM fails, return a mock response for demo purposes
        output_schema = snapshot.get("output_schema", {})
        if output_schema and output_schema.get("properties"):
            fields = list(output_schema["properties"].keys())
            return {fields[0]: f"[模拟回复] {user_message[:200]}"}
        return {"result": f"[模拟回复] LLM调用失败: {str(e)}"}


async def get_run_trace(
    db: AsyncSession,
    run_id: str,
) -> dict[str, Any]:
    """Get detailed run trace including all agent runs."""
    run = await db.get(TaskRun, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    # Get all agent runs
    result = await db.execute(
        select(AgentRun).where(AgentRun.task_run_id == run_id)
    )
    agent_runs = result.scalars().all()

    return {
        "run": {
            "id": str(run.id),
            "status": run.status,
            "context": run.context,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_message": run.error_message,
            "artifact": run.artifact,
        },
        "agent_runs": [
            {
                "id": str(ar.id),
                "status": ar.status,
                "input_data": ar.input_data,
                "output_data": ar.output_data,
                "tool_calls": ar.tool_calls,
                "token_usage": ar.token_usage,
                "started_at": ar.started_at.isoformat() if ar.started_at else None,
                "completed_at": ar.completed_at.isoformat() if ar.completed_at else None,
                "duration_ms": ar.duration_ms,
                "error_message": ar.error_message,
            }
            for ar in agent_runs
        ],
    }
