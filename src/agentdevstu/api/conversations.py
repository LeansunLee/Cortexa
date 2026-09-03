"""Conversation and Message API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.api.schemas import (
    ConversationCreate,
    ConversationOut,
    ConversationListOut,
    ConversationMessageCreate,
    ConversationMessageOut,
)
from agentdevstu.db.models import Agent, Conversation, ConversationMessage, Workspace

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationListOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[ConversationListOut]:
    query = select(Conversation).order_by(Conversation.created_at.desc())
    if workspace_id:
        query = query.where(Conversation.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    convs = list(result.scalars().all())

    # Enrich with agent info
    enriched = []
    for conv in convs:
        agent_name = None
        agent_avatar = None
        if conv.agent_id:
            agent = await db.get(Agent, conv.agent_id)
            if agent:
                agent_name = agent.name
                agent_avatar = agent.avatar
        enriched.append(ConversationListOut(
            id=conv.id, workspace_id=conv.workspace_id, agent_id=conv.agent_id,
            agent_name=agent_name, agent_avatar=agent_avatar,
            title=conv.title, status=conv.status,
            created_at=conv.created_at, updated_at=conv.updated_at,
        ))
    return enriched


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Conversation:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    conv = Conversation(
        workspace_id=uuid.UUID(workspace_id),
        agent_id=payload.agent_id,
        title=payload.title,
    )
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return conv


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.get("/{conv_id}/messages", response_model=list[ConversationMessageOut])
async def list_messages(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ConversationMessage]:
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conv_id)
        .order_by(ConversationMessage.created_at)
    )
    return list(result.scalars().all())


@router.post("/{conv_id}/messages", response_model=ConversationMessageOut, status_code=201)
async def create_message(
    conv_id: uuid.UUID,
    payload: ConversationMessageCreate,
    db: AsyncSession = Depends(get_db),
) -> ConversationMessage:
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    msg = ConversationMessage(
        conversation_id=conv_id,
        role="user",
        content=payload.content,
    )
    db.add(msg)
    
    # If there's an agent, generate response
    if conv.agent_id:
        agent = await db.get(Agent, conv.agent_id)
        if agent:
            try:
                from agentdevstu.config.llm_providers import create_llm
                import json
                
                model = create_llm(agent.model)
                
                # Build system prompt
                system_prompt = _build_system_prompt(agent)
                
                # Get conversation history
                history_result = await db.execute(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conv_id)
                    .order_by(ConversationMessage.created_at)
                )
                messages = list(history_result.scalars().all())
                
                # Prepare messages for LLM
                llm_messages = [{"role": "system", "content": system_prompt}]
                for m in messages:
                    llm_messages.append({"role": m.role, "content": m.content})
                llm_messages.append({"role": "user", "content": payload.content})
                
                # Call LLM or proxy
                if agent.agent_type == "proxy":
                    from agentdevstu.agents.proxy_executor import execute_proxy_agent
                    result = await execute_proxy_agent(agent, {"messages": [m.content for m in messages]}, db)
                    reply_content = str(result.get("output_data", {})) if result["success"] else f"代理调用失败：{result.get('error', 'unknown')}"
                else:
                    response = model.invoke(llm_messages)
                    reply_content = response.content if hasattr(response, 'content') else str(response)
                
                reply_msg = ConversationMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content=reply_content,
                )
                db.add(reply_msg)
            except Exception as e:
                error_msg = ConversationMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content=f"抱歉，处理请求时出错：{str(e)}",
                )
                db.add(error_msg)
    
    await db.flush()
    await db.refresh(msg)
    return msg


@router.delete("/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(conv)


def _build_system_prompt(agent: Agent) -> str:
    """Build system prompt from agent configuration."""
    parts = []
    if agent.name:
        parts.append(f"你是{agent.name}。")
    if agent.personality:
        parts.append(f"\n## 人格特征\n{agent.personality}")
    if agent.role:
        parts.append(f"\n## 角色\n{agent.role}")
    if agent.responsibilities:
        parts.append(f"\n## 职责\n{agent.responsibilities}")
    if agent.boundaries:
        parts.append(f"\n## 工作边界\n{agent.boundaries}")
    if agent.system_prompt:
        parts.append(f"\n## 补充说明\n{agent.system_prompt}")
    return "\n".join(parts) if parts else "你是一个AI助手。"
