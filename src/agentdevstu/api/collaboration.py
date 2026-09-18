"""Agent Collaboration API endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.collaboration.manager import (
    list_collaboration_agents,
    get_collaboration_history,
    check_collaboration_limits,
)
from agentdevstu.collaboration.schemas import CollaborationLimits

router = APIRouter(prefix="/collaboration", tags=["collaboration"])


@router.get("/agents")
async def get_collaboration_agents(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
    exclude_agent_id: str | None = None,
) -> list[dict[str, Any]]:
    """获取可协作的 Agent 列表（用于 @ 提及下拉）"""
    exclude_id = None
    if exclude_agent_id:
        try:
            exclude_id = uuid.UUID(exclude_agent_id)
        except ValueError:
            pass

    agents = await list_collaboration_agents(db, workspace_id, exclude_id)
    return agents


@router.get("/history/{conversation_id}")
async def get_history(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """获取对话的协作历史"""
    return await get_collaboration_history(db, conversation_id)


@router.get("/limits/{conversation_id}")
async def get_limits(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """检查对话的协作限制状态"""
    return await check_collaboration_limits(db, conversation_id)


@router.get("/draft-options")
async def draft_options(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from agentdevstu.security.access import require_agent_use, actor_required
    agent = await require_agent_use(db, agent_id)
    can_read = actor_required().has("agent.read")
    return {"agent_type": agent.agent_type, "can_read_config": can_read,
            "supplemental_prompt": (agent.proxy_config or {}).get("supplemental_prompt", "") if can_read else None}


from pydantic import BaseModel
from agentdevstu.collaboration.drafts import CollaborationDraft

class DraftPreview(BaseModel):
    conversation_id: uuid.UUID
    draft: CollaborationDraft
    main_input: str = ""


@router.post("/preview")
async def preview_draft(payload: DraftPreview, db: AsyncSession = Depends(get_db)):
    from agentdevstu.security.access import require_agent_use
    from agentdevstu.db.models import Conversation, Workspace
    from agentdevstu.collaboration.schemas import AgentHandoff
    from agentdevstu.collaboration.drafts import proxy_request, visible_snapshot
    from agentdevstu.agents.prompts import build_system_prompt, handoff_message, reference_message
    from agentdevstu.agents.proxy_executor import build_proxy_body
    conv = await db.get(Conversation, payload.conversation_id)
    if not conv or not conv.agent_id:
        raise HTTPException(404, "对话不存在")
    source = await require_agent_use(db, conv.agent_id)
    target = await require_agent_use(db, payload.draft.agent_id)
    if source.id == target.id or source.agent_type == "proxy":
        raise HTTPException(422, "请选择其他 Agent，由 LLM 主 Agent 发起协作")
    draft = payload.draft
    from agentdevstu.collaboration.background import prepare_background, background_messages
    background = await prepare_background(db, conv.id, draft, payload.main_input, target_type=target.agent_type)
    if background["status"] != "ready":
        return {"snapshot": {}, "background": background, "note": background["reason"]}
    handoff = AgentHandoff(source_agent_id=str(source.id), target_agent_id=str(target.id),
        task=draft.task, question=draft.task, constraints=draft.constraints,
        expected_output=draft.expected_output, supplemental_prompt=draft.supplemental_prompt, background_context=background)
    if target.agent_type == "proxy":
        try:
            snapshot = {"type": "proxy", "request_body": build_proxy_body(target.proxy_config or {}, {"input": proxy_request(handoff)}, draft.supplemental_prompt)}
        except ValueError as error:
            raise HTTPException(422, str(error))
    else:
        workspace = await db.get(Workspace, target.workspace_id)
        snapshot = {"type": "llm", "messages": [{"role": "system", "content": build_system_prompt(target, workspace)}, *background_messages(background), handoff_message(handoff)]}
    return {"snapshot": visible_snapshot(snapshot), "note": "这是当前配置预览。执行时会追加前置任务结果；LLM 还可能加入历史、知识及工具说明。实际初始输入在执行记录中保存。"}


@router.get("/input/{conversation_id}")
async def get_input_snapshot(conversation_id: uuid.UUID, snapshot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from agentdevstu.db.models import Conversation
    from agentdevstu.collaboration.drafts import read_input_snapshot, visible_snapshot
    if not await db.get(Conversation, conversation_id):
        raise HTTPException(404, "对话不存在")
    try:
        return visible_snapshot(await read_input_snapshot(conversation_id, snapshot_id))
    except FileNotFoundError:
        raise HTTPException(404, "输入快照不存在")


class BackgroundPreview(DraftPreview):
    main_input: str = ""
    earlier_agent_ids: list[uuid.UUID] = []


@router.post("/background")
async def preview_background(payload: BackgroundPreview, db: AsyncSession = Depends(get_db)):
    from types import SimpleNamespace
    from agentdevstu.security.access import require_agent_use
    from agentdevstu.db.models import Conversation
    from agentdevstu.collaboration.background import prepare_background, background_messages
    conv = await db.get(Conversation, payload.conversation_id)
    if not conv or not conv.agent_id:
        raise HTTPException(404, "对话不存在")
    source = await require_agent_use(db, conv.agent_id)
    collaboration_target = await require_agent_use(db, payload.draft.agent_id)
    if source.id == payload.draft.agent_id or source.agent_type == "proxy":
        raise HTTPException(422, "请选择其他 Agent，由 LLM 主 Agent 发起协作")
    if len(payload.earlier_agent_ids) > 3 or len(payload.main_input) > 12000:
        raise HTTPException(422, "预览内容超过长度限制")
    prior = []
    for agent_id in payload.earlier_agent_ids:
        target = await require_agent_use(db, agent_id)
        prior.append({"agent_id": str(agent_id), "agent_name": target.name, "result": SimpleNamespace(status="pending")})
    return await prepare_background(db, conv.id, payload.draft, payload.main_input, target_type=collaboration_target.agent_type)
