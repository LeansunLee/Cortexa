"""Workflow editing, publication, and execution API."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cortexa.api.deps import get_db, get_current_workspace
from cortexa.api.schemas import (
    TaskRunOut, WorkflowCreate, WorkflowDetailOut, WorkflowEdgeCreate,
    WorkflowEdgeOut, WorkflowNodeCreate, WorkflowNodeOut, WorkflowRunCreate,
    WorkflowUpdate,
)
from cortexa.db.models import Task, TaskRun, Workflow, WorkflowEdge, WorkflowNode
from cortexa.security.access import actor_required, require, require_agent_use
from cortexa.workflow.engine import ordered_nodes, run_task

router = APIRouter(prefix="/workflows", tags=["workflows"])


async def _workflow(db: AsyncSession, wf_id: uuid.UUID) -> Workflow:
    require("workflows.manage")
    wf = await db.scalar(
        select(Workflow).where(Workflow.id == wf_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    if not wf or wf.workspace_id != actor_required().workspace_id:
        raise HTTPException(404, "工作流不存在")
    return wf


@router.get("", response_model=list[WorkflowDetailOut])
async def list_workflows(db: AsyncSession = Depends(get_db), workspace_id: str | None = Depends(get_current_workspace)):
    require("workflows.manage")
    if not workspace_id:
        raise HTTPException(400, "请先选择工作空间")
    rows = await db.scalars(
        select(Workflow).where(Workflow.workspace_id == uuid.UUID(workspace_id))
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
        .order_by(Workflow.created_at.desc())
    )
    return list(rows.all())


@router.post("", response_model=WorkflowDetailOut, status_code=201)
async def create_workflow(payload: WorkflowCreate, db: AsyncSession = Depends(get_db), workspace_id: str | None = Depends(get_current_workspace)):
    require("workflows.manage")
    if not workspace_id:
        raise HTTPException(400, "请先选择工作空间")
    wf = Workflow(workspace_id=uuid.UUID(workspace_id), name=payload.name.strip(), description=payload.description)
    db.add(wf)
    await db.flush()
    return await _workflow(db, wf.id)


@router.get("/{wf_id}", response_model=WorkflowDetailOut)
async def get_workflow(wf_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await _workflow(db, wf_id)


@router.patch("/{wf_id}", response_model=WorkflowDetailOut)
async def update_workflow(wf_id: uuid.UUID, payload: WorkflowUpdate, db: AsyncSession = Depends(get_db)):
    wf = await _workflow(db, wf_id)
    if payload.name is not None:
        wf.name = payload.name.strip()
    if "description" in payload.model_fields_set:
        wf.description = payload.description
    if payload.status == "active":
        try:
            steps = ordered_nodes(wf.nodes, wf.edges)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        for step in steps:
            await require_agent_use(db, step.agent_id)
    if payload.status:
        wf.status = payload.status
    await db.flush()
    return wf


@router.post("/{wf_id}/nodes", response_model=WorkflowNodeOut, status_code=201)
async def add_node(wf_id: uuid.UUID, payload: WorkflowNodeCreate, db: AsyncSession = Depends(get_db)):
    wf = await _workflow(db, wf_id)
    await require_agent_use(db, payload.agent_id)
    name = payload.name.strip()
    if any(node.name.casefold() == name.casefold() for node in wf.nodes):
        raise HTTPException(409, "步骤名称不能重复")
    node = WorkflowNode(workflow_id=wf.id, agent_id=payload.agent_id, name=name, type="agent", position_x=len(wf.nodes) * 200)
    db.add(node)
    wf.status = "draft"
    await db.flush()
    await db.refresh(node)
    return node


@router.delete("/{wf_id}/nodes/{node_id}", status_code=204)
async def delete_node(wf_id: uuid.UUID, node_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    wf = await _workflow(db, wf_id)
    node = next((item for item in wf.nodes if item.id == node_id), None)
    if not node:
        raise HTTPException(404, "步骤不存在")
    for edge in wf.edges:
        if node_id in (edge.source_node_id, edge.target_node_id):
            await db.delete(edge)
    await db.delete(node)
    wf.status = "draft"


@router.post("/{wf_id}/edges", response_model=WorkflowEdgeOut, status_code=201)
async def add_edge(wf_id: uuid.UUID, payload: WorkflowEdgeCreate, db: AsyncSession = Depends(get_db)):
    wf = await _workflow(db, wf_id)
    ids = {node.id for node in wf.nodes}
    if payload.source_node_id not in ids or payload.target_node_id not in ids or payload.source_node_id == payload.target_node_id:
        raise HTTPException(422, "连接的步骤无效")
    if any(edge.source_node_id == payload.source_node_id or edge.target_node_id == payload.target_node_id for edge in wf.edges):
        raise HTTPException(422, "当前仅支持顺序连接的工作流")
    next_by_source = {edge.source_node_id: edge.target_node_id for edge in wf.edges}
    cursor = payload.target_node_id
    while cursor in next_by_source:
        cursor = next_by_source[cursor]
        if cursor == payload.source_node_id:
            raise HTTPException(422, "工作流不能形成循环")
    edge = WorkflowEdge(workflow_id=wf.id, source_node_id=payload.source_node_id, target_node_id=payload.target_node_id)
    db.add(edge)
    wf.status = "draft"
    await db.flush()
    await db.refresh(edge)
    return edge


@router.delete("/{wf_id}/edges/{edge_id}", status_code=204)
async def delete_edge(wf_id: uuid.UUID, edge_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    wf = await _workflow(db, wf_id)
    edge = next((item for item in wf.edges if item.id == edge_id), None)
    if not edge:
        raise HTTPException(404, "连接不存在")
    await db.delete(edge)
    wf.status = "draft"


@router.post("/{wf_id}/run", response_model=TaskRunOut, status_code=201)
async def run_workflow(wf_id: uuid.UUID, payload: WorkflowRunCreate, db: AsyncSession = Depends(get_db)):
    wf = await _workflow(db, wf_id)
    if wf.status != "active":
        raise HTTPException(409, "请先发布工作流")
    try:
        nodes = ordered_nodes(wf.nodes, wf.edges)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    for node in nodes:
        await require_agent_use(db, node.agent_id)
    task = Task(
        workspace_id=wf.workspace_id,
        owner_user_id=actor_required().user_id,
        agent_id=nodes[0].agent_id,
        name=wf.name,
        description=wf.description,
        input_data=payload.input_data,
        status="pending",
    )
    db.add(task)
    await db.flush()
    return await run_task(db, task, [(node.name, node.agent_id) for node in nodes], wf.id)


@router.get("/{wf_id}/runs", response_model=list[TaskRunOut])
async def list_workflow_runs(wf_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _workflow(db, wf_id)
    rows = await db.scalars(select(TaskRun).where(TaskRun.workflow_id == wf_id).order_by(TaskRun.started_at.desc()).limit(50))
    return list(rows.all())


@router.delete("/{wf_id}", status_code=204)
async def delete_workflow(wf_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    wf = await _workflow(db, wf_id)
    runs = await db.scalars(select(TaskRun).where(TaskRun.workflow_id == wf.id))
    for run in runs.all():
        run.workflow_id = None
    await db.delete(wf)
