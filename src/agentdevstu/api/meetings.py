"""Meeting CRUD + Runtime + SSE API."""

from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.db.models import Agent
from pathlib import Path

from agentdevstu.db.meetings import (
    Meeting, MeetingParticipant, MeetingRound,
    MeetingMessage, MeetingConclusion, TodoItem,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


# ── Schemas ──────────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    topic: str
    purpose: str = "analysis"
    title: str | None = None
    host_agent_id: uuid.UUID | None = None
    participant_agent_ids: list[uuid.UUID] = Field(default_factory=list)
    max_rounds: int = 3
    attachments: list[dict] = Field(default_factory=list, description="附件列表 [{name, path, size, type}]")


class MeetingOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str | None
    topic: str
    purpose: str
    host_agent_id: uuid.UUID | None
    status: str
    max_rounds: int
    current_round: int
    attachments: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class MeetingDetailOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str | None
    topic: str
    purpose: str
    host_agent_id: uuid.UUID | None
    status: str
    max_rounds: int
    current_round: int
    participants: list[ParticipantOut]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ParticipantOut(BaseModel):
    id: uuid.UUID
    participant_type: str
    agent_id: uuid.UUID | None
    name: str
    role: str | None
    is_host: bool
    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: uuid.UUID
    round_number: int
    sender_type: str
    sender_agent_id: uuid.UUID | None
    sender_name: str
    content: str
    message_type: str
    created_at: datetime
    model_config = {"from_attributes": True}


class RoundOut(BaseModel):
    id: uuid.UUID
    round_number: int
    topic: str | None
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


class ConclusionOut(BaseModel):
    id: uuid.UUID
    summary: str
    key_decisions: list[Any]
    disagreements: list[Any]
    created_at: datetime
    model_config = {"from_attributes": True}


class TodoOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    assignee_type: str
    assignee_name: str | None
    priority: str
    status: str
    due_date: str | None
    model_config = {"from_attributes": True}


class MeetingCancel(BaseModel):
    reason: str | None = None



# ── File Upload ───────────────────────────────────────────────────

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads" / "meetings"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload")
async def upload_meeting_file(
    file: UploadFile = FastAPIFile(...),
) -> dict:
    """Upload a file for meeting attachment."""
    import hashlib
    content_bytes = await file.read()
    ext = Path(file.filename or "file").suffix
    file_hash = hashlib.md5(content_bytes).hexdigest()[:8]
    safe_name = f"{file_hash}_{file.filename}" if file.filename else f"{file_hash}_file"
    save_path = UPLOAD_DIR / safe_name
    save_path.write_bytes(content_bytes)
    return {
        "name": file.filename,
        "path": f"/uploads/meetings/{safe_name}",
        "size": len(content_bytes),
        "type": file.content_type or "application/octet-stream",
    }


# ── CRUD ──────────────────────────────────────────────────────────

@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[Meeting]:
    query = select(Meeting).order_by(Meeting.created_at.desc())
    if workspace_id:
        query = query.where(Meeting.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=MeetingOut, status_code=201)
async def create_meeting(
    payload: MeetingCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Meeting:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    meeting = Meeting(
        workspace_id=uuid.UUID(workspace_id),
        topic=payload.topic,
        purpose=payload.purpose,
        title=payload.title,
        host_agent_id=payload.host_agent_id,
        max_rounds=payload.max_rounds,
        attachments=payload.attachments,
        status="preparing",
    )
    db.add(meeting)
    await db.flush()

    # Add participants
    for agent_id in payload.participant_agent_ids:
        agent = await db.get(Agent, agent_id)
        if agent:
            is_host = (agent_id == payload.host_agent_id)
            participant = MeetingParticipant(
                meeting_id=meeting.id,
                participant_type="agent",
                agent_id=agent_id,
                name=agent.name,
                role=agent.role,
                is_host=is_host,
            )
            db.add(participant)

    # If no host specified, first participant is host
    if not payload.host_agent_id:
        result = await db.execute(
            select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id).limit(1)
        )
        first = result.scalar_one_or_none()
        if first:
            first.is_host = True
            meeting.host_agent_id = first.agent_id

    await db.flush()
    await db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}", response_model=MeetingDetailOut)
async def get_meeting(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MeetingDetailOut:
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    result = await db.execute(
        select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
    )
    participants = list(result.scalars().all())

    return MeetingDetailOut(
        id=meeting.id, workspace_id=meeting.workspace_id, title=meeting.title,
        topic=meeting.topic, purpose=meeting.purpose, host_agent_id=meeting.host_agent_id,
        status=meeting.status, max_rounds=meeting.max_rounds, current_round=meeting.current_round,
        participants=[ParticipantOut.model_validate(p) for p in participants],
        created_at=meeting.created_at, updated_at=meeting.updated_at,
    )


@router.get("/{meeting_id}/messages", response_model=list[MessageOut])
async def list_messages(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    result = await db.execute(
        select(MeetingMessage).where(MeetingMessage.meeting_id == meeting_id)
        .order_by(MeetingMessage.created_at)
    )
    return list(result.scalars().all())


@router.get("/{meeting_id}/conclusion", response_model=ConclusionOut | None)
async def get_conclusion(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ConclusionOut | None:
    result = await db.execute(
        select(MeetingConclusion).where(MeetingConclusion.meeting_id == meeting_id)
    )
    conc = result.scalar_one_or_none()
    if not conc:
        return None
    return ConclusionOut.model_validate(conc)


@router.get("/{meeting_id}/todos", response_model=list[TodoOut])
async def list_todos(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[TodoOut]:
    result = await db.execute(
        select(TodoItem).where(TodoItem.meeting_id == meeting_id)
        .order_by(TodoItem.created_at)
    )
    return list(result.scalars().all())


@router.post("/{meeting_id}/cancel", response_model=MeetingOut)
async def cancel_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingCancel | None = None,
    db: AsyncSession = Depends(get_db),
) -> Meeting:
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting.status = "cancelled"
    await db.flush()
    await db.refresh(meeting)
    return meeting


# ── SSE Meeting Runtime ───────────────────────────────────────────

# In-memory meeting state (for MVP; later move to Redis)
_meeting_tasks: dict[str, asyncio.Task] = {}


@router.post("/{meeting_id}/start")
async def start_meeting(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start meeting runtime and return SSE stream URL."""
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status not in ("preparing", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Meeting status is {meeting.status}")

    meeting.status = "running"
    meeting.current_round = 0
    await db.flush()

    return {"meeting_id": str(meeting_id), "stream_url": f"/api/meetings/{meeting_id}/stream"}


@router.get("/{meeting_id}/stream")
async def stream_meeting(
    meeting_id: uuid.UUID,
):
    """SSE endpoint for real-time meeting updates."""
    async def event_generator() -> AsyncGenerator[str, None]:
        from agentdevstu.db.engine import async_session_factory
        async with async_session_factory() as db:
            meeting = await db.get(Meeting, meeting_id)
            if not meeting:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Meeting not found'})}\n\n"
                return

            # Get participants and host
            result = await db.execute(
                select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
            )
            participants = list(result.scalars().all())
            host = next((p for p in participants if p.is_host), participants[0] if participants else None)
            non_host = [p for p in participants if not p.is_host]

            if not non_host:
                yield f"data: {json.dumps({'type': 'error', 'error': 'No participants'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'start', 'meeting_id': str(meeting_id), 'rounds': meeting.max_rounds})}\n\n"

            try:
                from agentdevstu.config.llm_providers import create_llm

                # Build meeting context
                all_messages: list[dict[str, str]] = []
                conflict_detected = False

                for round_num in range(1, meeting.max_rounds + 1):
                    meeting.current_round = round_num
                    round_obj = MeetingRound(
                        meeting_id=meeting_id,
                        round_number=round_num,
                        topic=f"Round {round_num}" + (": 针对性追问" if round_num > 1 else ": 独立分析"),
                        status="running",
                    )
                    db.add(round_obj)
                    await db.flush()

                    yield f"data: {json.dumps({'type': 'round_start', 'round': round_num, 'topic': round_obj.topic})}\n\n"

                    # Phase 1: Each non-host agent analyzes independently
                    for p in non_host:
                        agent = await db.get(Agent, p.agent_id) if p.agent_id else None
                        if not agent:
                            continue

                        system_prompt = _build_agent_meeting_prompt(agent, meeting.topic, meeting.purpose, meeting.attachments)
                        user_content = _build_round_user_content(meeting.topic, round_num, all_messages, conflict_detected)

                        yield f"data: {json.dumps({'type': 'agent_thinking', 'round': round_num, 'agent': p.name, 'agent_id': str(p.agent_id)})}\n\n"

                        try:
                            model = create_llm(agent.model)
                            response = model.invoke([
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_content},
                            ])
                            agent_reply = response.content if hasattr(response, 'content') else str(response)
                        except Exception as e:
                            agent_reply = f"[分析失败: {str(e)}]"

                        # Save message
                        msg = MeetingMessage(
                            meeting_id=meeting_id, round_number=round_num,
                            sender_type="agent", sender_agent_id=p.agent_id,
                            sender_name=p.name, content=agent_reply,
                            message_type="analysis",
                        )
                        db.add(msg)
                        await db.flush()

                        all_messages.append({"role": p.name, "content": agent_reply, "round": round_num})

                        yield f"data: {json.dumps({'type': 'agent_message', 'round': round_num, 'agent': p.name, 'agent_id': str(p.agent_id), 'content': agent_reply, 'message_id': str(msg.id)})}\n\n"

                    # Phase 2: Host summarizes and checks for conflicts
                    if host and host.agent_id:
                        host_agent = await db.get(Agent, host.agent_id)
                        if host_agent:
                            yield f"data: {json.dumps({'type': 'host_thinking', 'round': round_num, 'agent': host.name})}\n\n"

                            summary_prompt = _build_host_summary_prompt(host_agent, meeting.topic, round_num, meeting.max_rounds)
                            history_text = "\n\n".join([
                                f"【{m['role']}】(Round {m['round']}):\n{m['content']}" for m in all_messages
                            ])

                            try:
                                model = create_llm(host_agent.model)
                                response = model.invoke([
                                    {"role": "system", "content": summary_prompt},
                                    {"role": "user", "content": history_text},
                                ])
                                host_summary = response.content if hasattr(response, 'content') else str(response)
                            except Exception as e:
                                host_summary = f"[主持人汇总失败: {str(e)}]"

                            # Check for conflicts (simple heuristic)
                            conflict_detected = any(kw in host_summary.lower() for kw in ["冲突", "分歧", "矛盾", "不一致", "不同意", "争议"])

                            host_msg_type = "summary" if not conflict_detected else "question"
                            msg = MeetingMessage(
                                meeting_id=meeting_id, round_number=round_num,
                                sender_type="host", sender_agent_id=host.agent_id,
                                sender_name=host.name, content=host_summary,
                                message_type=host_msg_type,
                            )
                            db.add(msg)
                            await db.flush()

                            all_messages.append({"role": host.name, "content": host_summary, "round": round_num, "type": host_msg_type})

                            yield f"data: {json.dumps({'type': 'host_message', 'round': round_num, 'agent': host.name, 'content': host_summary, 'message_type': host_msg_type, 'conflict': conflict_detected, 'message_id': str(msg.id)})}\n\n"

                    # Update round status
                    round_obj.status = "completed"
                    await db.commit()

                    # Check if we should stop
                    if not conflict_detected or round_num >= meeting.max_rounds:
                        break

                    yield f"data: {json.dumps({'type': 'round_continue', 'round': round_num, 'reason': 'conflict_detected'})}\n\n"

                # Phase 3: Generate conclusion
                yield f"data: {json.dumps({'type': 'conclusion_start'})}\n\n"

                conclusion_text = _generate_conclusion_sync(meeting.topic, all_messages)

                conclusion = MeetingConclusion(
                    meeting_id=meeting_id,
                    summary=conclusion_text,
                    key_decisions=[],
                    disagreements=[],
                )
                db.add(conclusion)
                await db.commit()

                yield f"data: {json.dumps({'type': 'conclusion', 'content': conclusion_text, 'conclusion_id': str(conclusion.id)})}\n\n"

                # Phase 4: Generate TodoList
                yield f"data: {json.dumps({'type': 'todos_start'})}\n\n"

                todos = _generate_todos_sync(meeting.topic, conclusion_text, participants)

                todo_items = []
                for t in todos:
                    todo = TodoItem(
                        meeting_id=meeting_id,
                        workspace_id=meeting.workspace_id,
                        title=t["title"],
                        description=t.get("description"),
                        assignee_type="agent",
                        assignee_agent_id=t.get("assignee_agent_id"),
                        assignee_name=t.get("assignee_name"),
                        priority=t.get("priority", "medium"),
                    )
                    db.add(todo)
                    todo_items.append(t)
                await db.commit()

                yield f"data: {json.dumps({'type': 'todos', 'items': todo_items})}\n\n"

                # Mark meeting as completed
                meeting.status = "completed"
                await db.commit()

                yield f"data: {json.dumps({'type': 'complete', 'meeting_id': str(meeting_id)})}\n\n"

            except Exception as e:
                tb = traceback.format_exc()
                print(f"[Meeting Runtime Error] {e}\n{tb}")
                meeting.status = "failed"
                await db.commit()
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Prompt Builders ───────────────────────────────────────────────

def _read_attachments(attachments: list) -> str:
    """Read attachment file contents for context injection."""
    if not attachments:
        return ""
    parts = ["\n## 参考材料"]
    base = Path(__file__).resolve().parents[3]
    for att in attachments:
        name = att.get("name", "unknown")
        path = att.get("path", "")
        if not path:
            continue
        full = base / path.lstrip("/")
        if not full.exists():
            parts.append(f"### {name}\n[文件不存在]")
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
            # Truncate long files
            if len(text) > 3000:
                text = text[:3000] + "\n... [已截断]"
            parts.append(f"### {name}\n{text}")
        except Exception:
            parts.append(f"### {name}\n[无法读取文件内容]")
    return "\n".join(parts)


def _build_agent_meeting_prompt(agent: Agent, topic: str, purpose: str, attachments: list | None = None) -> str:
    parts = [f"你正在参加一个 AI 会议。"]
    if agent.name:
        parts.append(f"你是{agent.name}。")
    if agent.role:
        parts.append(f"你的角色：{agent.role}")
    if agent.responsibilities:
        parts.append(f"你的职责：{agent.responsibilities}")
    if agent.boundaries:
        parts.append(f"工作边界：{agent.boundaries}")
    if agent.personality:
        parts.append(f"性格特征：{agent.personality}")

    purpose_map = {
        "decision": "做决策",
        "solution": "制定方案",
        "risk_assessment": "风险评估",
        "problem_solving": "解决问题",
        "analysis": "分析情况",
    }
    parts.append(f"\n会议议题：{topic}")
    parts.append(f"会议目标：{purpose_map.get(purpose, purpose)}")
    if attachments:
        attachment_text = _read_attachments(attachments)
        if attachment_text:
            parts.append(attachment_text)
    parts.append(f"\n请基于你的专业领域，对会议议题给出你的分析和建议。要求：")
    parts.append(f"1. 从你的专业角度出发")
    parts.append(f"2. 给出具体的观点和论据")
    parts.append(f"3. 如果发现其他参与者的观点有问题，明确指出")
    parts.append(f"4. 保持简洁，控制在 300 字以内")
    return "\n".join(parts)


def _build_host_summary_prompt(agent: Agent, topic: str, round_num: int, max_rounds: int) -> str:
    parts = [f"你是本次会议的主持人。"]
    if agent.name:
        parts[0] = f"你是{agent.name}，本次会议的主持人。"

    parts.append(f"\n会议议题：{topic}")
    parts.append(f"当前是第 {round_num}/{max_rounds} 轮讨论。")
    parts.append(f"\n请根据以上各参会者的分析，完成以下任务：")
    parts.append(f"1. 总结各方观点")
    parts.append(f"2. 指出达成的共识")
    parts.append(f"3. 指出存在的冲突或分歧（如果有）")
    parts.append(f"4. 如果有冲突且还有剩余轮次，提出针对性追问")
    parts.append(f"5. 如果是最后一轮或无冲突，给出总结性结论")
    parts.append(f"\n保持简洁，控制在 500 字以内。")
    return "\n".join(parts)


def _build_round_user_content(topic: str, round_num: int, history: list, conflict: bool) -> str:
    if round_num == 1:
        return f"会议议题：{topic}\n\n请给出你的专业分析。"

    parts = [f"会议议题：{topic}", f"这是第 {round_num} 轮讨论。"]
    if conflict:
        parts.append("上一轮讨论中发现了观点冲突或分歧，请针对这些问题给出你的进一步分析。")
    else:
        parts.append("请基于之前的讨论，给出你的补充意见。")

    # Include recent history for context
    recent = history[-6:] if len(history) > 6 else history
    if recent:
        parts.append("\n之前的讨论记录：")
        for m in recent:
            parts.append(f"\n【{m['role']}】:\n{m['content'][:500]}")

    return "\n".join(parts)


def _generate_conclusion_sync(topic: str, messages: list) -> str:
    """Generate conclusion using LLM (called within async context)."""
    try:
        from agentdevstu.config.llm_providers import create_llm
        model = create_llm()

        history = "\n\n".join([
            f"【{m['role']}】(Round {m['round']}):\n{m['content']}" for m in messages
        ])

        prompt = f"""你是一个会议总结专家。请根据以下会议讨论内容，生成会议结论。

会议议题：{topic}

讨论记录：
{history}

请输出以下格式的结论：
1. 会议结论（一段话总结）
2. 关键决策（列表）
3. 待跟进事项（列表）

保持简洁专业。"""

        response = model.invoke([{"role": "user", "content": prompt}])
        return response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        return f"结论生成失败：{str(e)}"


def _generate_todos_sync(topic: str, conclusion: str, participants: list) -> list[dict]:
    """Generate todo items using LLM."""
    try:
        from agentdevstu.config.llm_providers import create_llm
        model = create_llm()

        participant_info = "\n".join([
            f"- {p.name} ({p.role or '未指定角色'})" for p in participants
        ])

        prompt = f"""根据以下会议结论，生成待办事项列表。

会议议题：{topic}

会议结论：
{conclusion}

参会人员：
{participant_info}

请输出 JSON 数组格式的待办事项，每个事项包含：
- title: 任务标题
- description: 任务描述
- assignee_name: 负责人名称（从参会人员中选择最合适的）
- priority: 优先级 (high/medium/low)
- due_date: 建议截止日期 (YYYY-MM-DD 格式，基于今天 {datetime.now().strftime('%Y-%m-%d')} 推算)

只输出 JSON 数组，不要其他内容。"""

        response = model.invoke([{"role": "user", "content": prompt}])
        text = response.content if hasattr(response, 'content') else str(response)

        # Extract JSON from response
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(text)
    except Exception:
        return [{"title": topic, "description": "请根据会议结论手动创建待办事项", "priority": "medium"}]

