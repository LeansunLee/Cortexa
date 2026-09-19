"""Work API. Membership, row visibility, state and action authorization are server enforced."""

import io
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from agentdevstu.api.deps import get_db
from agentdevstu.security.access import require, require_agent_use
from agentdevstu.security.models import Membership, User
from agentdevstu.work import candidates
from agentdevstu.work import service as s
from agentdevstu.work.models import Work, WorkActivity, WorkCandidate, WorkDeliverable
from agentdevstu.work.schemas import (
    ExtractInput,
    KnowledgeInput,
    MemoryInput,
    ReviewInput,
    WorkInput,
    WorkLogInput,
    WorkLogUpdate,
)

from agentdevstu.organization.schemas import RecommendationInput
from agentdevstu.organization.service import recommend

router = APIRouter(tags=["works"])


@router.get("/works/members")
async def members(db: AsyncSession = Depends(get_db)):
    users = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.workspace_id == s.actor().workspace_id, User.status == "active")
            .order_by(User.display_name)
        )
    ).scalars()
    return [{"id": u.id, "name": u.display_name} for u in users]


@router.get("/works")
async def list_works(
    view: str = "assigned",
    search: str = "",
    status: str = "",
    priority: str = "",
    assignee_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    a = s.actor()
    q = select(Work).where(s.visibility(a))
    if view == "assigned":
        q = q.where(Work.assignee_type == "human", Work.assignee_id == a.user_id)
    elif view == "created":
        q = q.where(Work.creator_id == a.user_id)
    elif view == "review":
        from sqlalchemy import and_, not_, or_

        q = q.where(
            Work.status == "review",
            or_(Work.creator_id == a.user_id, Work.reviewer_id == a.user_id),
            not_(and_(Work.assignee_type == "human", Work.assignee_id == a.user_id)),
        )
    elif view != "all":
        raise HTTPException(422, "未知工作视图")
    if search:
        q = q.where(
            Work.title.icontains(search[:200], autoescape=True) | Work.goal.icontains(search[:200], autoescape=True)
        )
    if status:
        q = q.where(Work.status == status)
    if priority:
        q = q.where(Work.priority == priority)
    if assignee_id:
        q = q.where(Work.assignee_id == assignee_id)
    rows = (await db.execute(q.order_by(Work.updated_at.desc(), Work.id).limit(limit).offset(offset))).scalars()
    return [await s.output(db, w) for w in rows]


@router.post("/works", status_code=201)
async def create_work(payload: WorkInput, db: AsyncSession = Depends(get_db)):
    return await s.output(db, await s.create(db, payload))


@router.post("/works/assignee-recommendations")
async def assignee_recommendations(payload: RecommendationInput, db: AsyncSession = Depends(get_db)):
    return await recommend(db, payload.model_dump())


@router.get("/works/{work_id}")
async def detail(work_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await s.output(db, await s.get_work(db, work_id))


@router.patch("/works/{work_id}")
async def edit(work_id: uuid.UUID, payload: WorkInput, db: AsyncSession = Depends(get_db)):
    w = await s.get_work(db, work_id, lock=True)
    s.allowed(w, "edit")
    data = payload.model_dump()
    data["reviewer_id"] = data["reviewer_id"] or w.creator_id
    await s.validate_people(db, data)
    changes = {k: {"before": str(getattr(w, k)), "after": str(v)} for k, v in data.items() if getattr(w, k) != v}
    for k, v in data.items():
        setattr(w, k, v)
    w.status = "pending" if w.assignee_type == "agent" else "todo"
    await s.event(db, w, "edited", changes)
    return await s.output(db, w)


@router.post("/works/{work_id}/start")
async def start(work_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await s.output(db, await s.transition(db, await s.get_work(db, work_id, True), "start"))


@router.post("/works/{work_id}/approve")
async def approve(work_id: uuid.UUID, payload: ReviewInput, db: AsyncSession = Depends(get_db)):
    return await s.output(db, await s.transition(db, await s.get_work(db, work_id, True), "approve", payload.comment))


@router.post("/works/{work_id}/reject")
async def reject(work_id: uuid.UUID, payload: ReviewInput, db: AsyncSession = Depends(get_db)):
    return await s.output(db, await s.transition(db, await s.get_work(db, work_id, True), "reject", payload.comment))


@router.post("/works/{work_id}/cancel")
async def cancel(work_id: uuid.UUID, payload: ReviewInput, db: AsyncSession = Depends(get_db)):
    return await s.output(db, await s.transition(db, await s.get_work(db, work_id, True), "cancel", payload.comment))


@router.post("/works/{work_id}/submit")
async def submit(
    work_id: uuid.UUID,
    content: str = Form("", max_length=100000),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    w = await s.get_work(db, work_id, True)
    s.allowed(w, "submit")
    content = content.strip()
    raw = await file.read(50 * 1024 * 1024 + 1) if file else None
    if raw is not None and (not raw or len(raw) > 50 * 1024 * 1024):
        raise HTTPException(422, "文件不能为空且不得超过 50 MB")
    if not content and raw is None:
        raise HTTPException(422, "请填写交付说明或上传文件")
    stored = []
    try:
        for kind, blob, filename in [
            ("text", content.encode(), None),
            ("file", raw, Path(file.filename or "交付文件").name[:255] if file else None),
        ]:
            if not blob:
                continue
            d = WorkDeliverable(
                id=uuid.uuid4(),
                workspace_id=w.workspace_id,
                work_id=w.id,
                type=kind,
                content=content[:2000] if kind == "text" else "",
                filename=filename,
                submitted_by=s.actor().user_id,
                metadata_json={"size": len(blob)},
            )
            s.STORAGE.mkdir(parents=True, exist_ok=True)
            path = s.blob_path(d.id)
            stored.append(path)
            await run_in_threadpool(path.write_bytes, blob)
            db.add(d)
        w.status = "review"
        await s.event(db, w, "submitted", {"summary": content[:500], "filename": file.filename if file else None})
        await db.commit()
    except Exception:
        await db.rollback()
        for path in stored:
            path.unlink(missing_ok=True)
        raise
    return await s.output(db, w)


@router.get("/works/{work_id}/activities")
async def activities(work_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await s.get_work(db, work_id)
    rows = (
        await db.execute(
            select(WorkActivity, User.display_name)
            .join(User, User.id == WorkActivity.actor_id)
            .where(WorkActivity.work_id == work_id)
            .order_by(WorkActivity.created_at, WorkActivity.id)
        )
    ).all()
    return [
        {**s.serialize(row), "actor_name": name, "can_edit": row.action == "log" and can_edit_log(row)}
        for row, name in rows
    ]


def can_edit_log(row):
    a = s.actor()
    return row.actor_id == a.user_id or a.has("workspace.manage")


@router.post("/works/{work_id}/logs", status_code=201)
async def create_log(work_id: uuid.UUID, payload: WorkLogInput, db: AsyncSession = Depends(get_db)):
    w = await s.get_work(db, work_id, True)
    s.allowed(w, "log")
    row = WorkActivity(
        workspace_id=w.workspace_id,
        work_id=w.id,
        actor_id=s.actor().user_id,
        action="log",
        data_json={"content": payload.content, "version": 1},
    )
    db.add(row)
    w.updated_at = datetime.now(UTC)
    await db.flush()
    return s.serialize(row)


@router.patch("/works/{work_id}/logs/{ident}")
async def edit_log(work_id: uuid.UUID, ident: uuid.UUID, payload: WorkLogUpdate, db: AsyncSession = Depends(get_db)):
    w = await s.get_work(db, work_id, True)
    s.allowed(w, "log")
    row = (
        await db.execute(
            select(WorkActivity).where(
                WorkActivity.id == ident, WorkActivity.work_id == w.id, WorkActivity.action == "log"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "工作日志不存在")
    if not can_edit_log(row):
        raise HTTPException(403, "仅日志作者或空间管理员可编辑")
    data = row.data_json or {}
    if payload.version != data.get("version", 1):
        raise HTTPException(409, "日志已被更新，请重新加载后再编辑")
    row.data_json = {
        **data,
        "content": payload.content,
        "version": payload.version + 1,
        "edited_at": datetime.now(UTC).isoformat(),
    }
    await s.event(
        db, w, "log_edited", {"log_id": str(row.id), "before": data.get("content", ""), "after": payload.content}
    )
    return s.serialize(row)


@router.get("/works/{work_id}/deliverables")
async def deliverables(work_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await s.get_work(db, work_id)
    rows = (
        await db.execute(
            select(WorkDeliverable)
            .where(WorkDeliverable.work_id == work_id)
            .order_by(WorkDeliverable.created_at.desc())
        )
    ).scalars()
    result = []
    for row in rows:
        data = s.serialize(row)
        if row.type == "text" and s.blob_path(row.id).is_file():
            data["content"] = await run_in_threadpool(s.blob_path(row.id).read_text, encoding="utf-8")
        result.append(data)
    return result


async def delivery(db, work_id, ident):
    w = await s.get_work(db, work_id, True)
    d = (
        await db.execute(select(WorkDeliverable).where(WorkDeliverable.id == ident, WorkDeliverable.work_id == w.id))
    ).scalar_one_or_none()
    if not d:
        raise HTTPException(404, "交付物不存在")
    return w, d


@router.get("/works/{work_id}/deliverables/{ident}/download")
async def download(work_id: uuid.UUID, ident: uuid.UUID, db: AsyncSession = Depends(get_db)):
    w, d = await delivery(db, work_id, ident)
    path = s.blob_path(d.id)
    if not path.is_file():
        raise HTTPException(404, "交付文件不存在")
    return FileResponse(
        path,
        filename=d.filename or "交付说明.txt",
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.post("/works/{work_id}/deliverables/{ident}/knowledge")
async def knowledge(
    work_id: uuid.UUID,
    ident: uuid.UUID,
    payload: KnowledgeInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    from agentdevstu.api.knowledge import ingest_document
    from agentdevstu.db.models import KnowledgeBase

    w, d = await delivery(db, work_id, ident)
    s.allowed(w, "knowledge")
    kb = await db.get(KnowledgeBase, payload.knowledge_base_id)
    if not kb or kb.workspace_id != w.workspace_id:
        raise HTTPException(404, "目标知识库不存在或无权访问")
    key = str(kb.id)
    prior = (d.metadata_json or {}).get("knowledge", {})
    if key in prior:
        return {"document_id": prior[key], "existing": True}
    path = s.blob_path(d.id)
    if not path.is_file():
        raise HTTPException(404, "交付文件不存在")
    from starlette.datastructures import Headers

    raw = await run_in_threadpool(path.read_bytes)
    upload = UploadFile(
        file=io.BytesIO(raw),
        filename=d.filename or f"{w.title}.txt",
        headers=Headers({"content-type": "application/octet-stream" if d.type == "file" else "text/plain"}),
    )
    doc = await ingest_document(kb.id, background_tasks, upload, db, commit=False)
    d.metadata_json = {**(d.metadata_json or {}), "knowledge": {**prior, key: str(doc.id)}}
    await s.event(
        db, w, "knowledge", {"document_id": str(doc.id), "knowledge_base_id": key, "deliverable_id": str(d.id)}
    )
    await db.commit()
    return {"document_id": doc.id}


@router.post("/works/{work_id}/memory")
async def memory(work_id: uuid.UUID, payload: MemoryInput, db: AsyncSession = Depends(get_db)):
    from agentdevstu.memory.governance import ingest
    from agentdevstu.memory.evidence import Source, append_evidence
    from agentdevstu.memory.policy import digest
    w=await s.get_work(db,work_id,True)
    s.allowed(w,"memory")
    await require_agent_use(db,payload.agent_id)
    content=payload.content.strip()
    if not content:raise HTTPException(422,"请填写记忆内容")
    signature=digest([str(payload.agent_id),content,payload.type,payload.memory_kind,str(payload.deliverable_id)])
    previous=(await db.scalars(select(WorkActivity).where(WorkActivity.work_id==w.id,WorkActivity.action=="memory"))).all()
    for item in previous:
        data=item.data_json
        if data.get('request_hash')==signature or (data.get('agent_id')==str(payload.agent_id) and data.get('content')==content and data.get('type')==payload.type):
            return {'memory_id':data['memory_id'],'existing':True,'outcome':data.get('outcome','existing')}
    acceptance=await db.scalar(select(WorkActivity).where(WorkActivity.work_id==w.id,WorkActivity.action=='approved').order_by(WorkActivity.created_at.desc()).limit(1))
    deliverable=None
    if payload.deliverable_id:
        deliverable=await db.scalar(select(WorkDeliverable).where(WorkDeliverable.id==payload.deliverable_id,WorkDeliverable.work_id==w.id))
        if not deliverable:raise HTTPException(404,'交付物不存在或无权访问')
    confirmed_outcome=bool(acceptance and payload.type=='episodic' and content==f'工作「{w.title}」已验收通过。')
    source=Source('work',str(w.id),sub_type='work_activity' if acceptance else None,
        sub_id=str(acceptance.id) if acceptance else None,revision=str(acceptance.id) if acceptance else None,
        mode='system' if confirmed_outcome else 'explicit',user_id=s.actor().user_id)
    mem=await ingest(db,payload.agent_id,{'content':content,'type':payload.type,
        'memory_kind':payload.memory_kind or ('outcome' if payload.type=='episodic' else 'fact'),
        'importance':.7,'source_mode':source.mode,'occurred_at':w.completed_at if payload.type=='episodic' else None,
        'subject_type':'work','subject_id':str(w.id),'subject_name':w.title},source)
    if deliverable:
        await append_evidence(db,mem,Source('work_deliverable',str(deliverable.id),mode='explicit',
            user_id=deliverable.submitted_by,roots=[source.key]))
    outcome=getattr(mem,'governance_outcome','created')
    await s.event(db,w,'memory',{'memory_id':str(mem.id),'agent_id':str(payload.agent_id),
        'type':payload.type,'request_hash':signature,'outcome':outcome})
    return {'memory_id':mem.id,'outcome':outcome,'status':mem.status,'existing':outcome in {'merged','existing'}}


@router.get("/conversations/{conv_id}/work-candidates")
async def list_candidates(conv_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await candidates.conversation(db, conv_id)
    rows = (
        await db.execute(
            select(WorkCandidate)
            .where(WorkCandidate.conversation_id == conv_id, WorkCandidate.owner_user_id == s.actor().user_id)
            .order_by(WorkCandidate.created_at)
        )
    ).scalars()
    return [s.serialize(c) for c in rows]


@router.post("/conversations/{conv_id}/work-candidates/extract")
async def extract_candidates(conv_id: uuid.UUID, payload: ExtractInput, db: AsyncSession = Depends(get_db)):
    require("agent.use")
    await candidates.extract(db, conv_id, payload.message_id)
    return await list_candidates(conv_id, db)


async def candidate(db, ident):
    a = s.actor()
    c = (
        await db.execute(
            select(WorkCandidate)
            .where(
                WorkCandidate.id == ident,
                WorkCandidate.workspace_id == a.workspace_id,
                WorkCandidate.owner_user_id == a.user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "工作建议不存在或无权访问")
    return c


@router.post("/work-candidates/{ident}/accept")
async def accept_candidate(ident: uuid.UUID, payload: WorkInput, db: AsyncSession = Depends(get_db)):
    c = await candidate(db, ident)
    if c.status == "accepted":
        return await s.output(db, await s.get_work(db, c.work_id))
    if c.status != "candidate":
        raise HTTPException(409, "该建议已忽略")
    conv = await candidates.conversation(db, c.conversation_id)
    from agentdevstu.db.models import ConversationMessage

    msg = await db.get(ConversationMessage, c.message_id)
    if not msg:
        raise HTTPException(404, "来源消息已删除")
    w = await s.create(
        db,
        payload,
        {
            "source_type": "agent_collaboration" if (msg.metadata_json or {}).get("collaborations") else "conversation",
            "source_id": conv.id,
            "source_message_id": msg.id,
            "source_label": conv.title or "Agent 对话",
            "source_excerpt": msg.content[:1000],
        },
    )
    c.status, c.work_id = "accepted", w.id
    await db.flush()
    return await s.output(db, w)


@router.post("/work-candidates/{ident}/reject")
async def ignore_candidate(ident: uuid.UUID, db: AsyncSession = Depends(get_db)):
    c = await candidate(db, ident)
    if c.status == "accepted":
        raise HTTPException(409, "该建议已创建工作")
    c.status = "rejected"
    await db.flush()
    return {"status": c.status}
