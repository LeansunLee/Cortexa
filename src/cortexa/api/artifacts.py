"""对话产出物 API：列表 / 详情 / 编辑 / 下载 / 转工作交付物 / 存入知识库。

可见与下载范围仅限会话所有者（与对话本身的 owner 隔离一致）。
"""
import io
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, UploadFile

from cortexa.api.deps import get_db
from cortexa.conversation import artifacts as store
from cortexa.db.models import Conversation, ConversationArtifact
from cortexa.security.access import actor_required

router = APIRouter()
CONTENT_PREVIEW_LIMIT = 400_000


async def owned_conversation(db, conv_id):
    a = actor_required()
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.workspace_id == a.workspace_id,
                Conversation.owner_user_id == a.user_id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "对话不存在或无权访问")
    return conv


async def owned_artifact(db, conv_id, artifact_id):
    conv = await owned_conversation(db, conv_id)
    row = (
        await db.execute(
            select(ConversationArtifact).where(
                ConversationArtifact.id == artifact_id,
                ConversationArtifact.conversation_id == conv_id,
                ConversationArtifact.owner_user_id == actor_required().user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "产出物不存在或无权访问")
    return conv, row


def _out(row) -> dict:
    return {
        "id": str(row.id),
        "conversation_id": str(row.conversation_id),
        "message_id": str(row.message_id) if row.message_id else None,
        "title": row.title,
        "filename": row.filename,
        "format": row.format,
        "size": row.byte_size,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/conversations/{conv_id}/artifacts")
async def list_artifacts(conv_id: uuid.UUID, db=Depends(get_db)):
    await owned_conversation(db, conv_id)
    rows = (
        await db.execute(
            select(ConversationArtifact)
            .where(
                ConversationArtifact.conversation_id == conv_id,
                ConversationArtifact.owner_user_id == actor_required().user_id,
            )
            .order_by(ConversationArtifact.created_at.desc())
            .limit(200)
        )
    ).scalars()
    return [_out(row) for row in rows]


@router.get("/conversations/{conv_id}/artifacts/{artifact_id}")
async def artifact_detail(conv_id: uuid.UUID, artifact_id: uuid.UUID, db=Depends(get_db)):
    _conv, row = await owned_artifact(db, conv_id, artifact_id)
    path = store.resolve_path(row)
    content = None
    truncated = False
    if path.is_file():
        raw = await run_in_threadpool(path.read_bytes)
        text = raw.decode("utf-8", errors="replace")
        if len(text) > CONTENT_PREVIEW_LIMIT:
            text, truncated = text[:CONTENT_PREVIEW_LIMIT], True
        content = text
    else:
        raise HTTPException(404, "产出文件不存在")
    return {**_out(row), "content": content, "truncated": truncated}


class ArtifactUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)


@router.patch("/conversations/{conv_id}/artifacts/{artifact_id}")
async def update_artifact(conv_id: uuid.UUID, artifact_id: uuid.UUID, payload: ArtifactUpdate, db=Depends(get_db)):
    _conv, row = await owned_artifact(db, conv_id, artifact_id)
    if payload.title is not None:
        row.title = payload.title[:200]
    if payload.content is not None:
        try:
            size, digest = await run_in_threadpool(store.overwrite, row.id, payload.content)
        except ValueError as error:
            raise HTTPException(422, str(error))
        row.byte_size = size
        row.content_sha256 = digest
    from sqlalchemy import func as sqlfunc

    row.updated_at = sqlfunc.now()
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.get("/conversations/{conv_id}/artifacts/{artifact_id}/download")
async def download_artifact(conv_id: uuid.UUID, artifact_id: uuid.UUID, db=Depends(get_db)):
    _conv, row = await owned_artifact(db, conv_id, artifact_id)
    path = store.resolve_path(row)
    if not path.is_file():
        raise HTTPException(404, "产出文件不存在")
    return FileResponse(
        path,
        filename=row.filename or "文档.md",
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


class DeliverableInput(BaseModel):
    work_id: uuid.UUID


@router.post("/conversations/{conv_id}/artifacts/{artifact_id}/deliverable", status_code=201)
async def to_deliverable(conv_id: uuid.UUID, artifact_id: uuid.UUID, payload: DeliverableInput, db=Depends(get_db)):
    """把产出物复制为某个工作的文本交付物（独立副本，后续编辑互不影响）。"""
    from cortexa.db.models import WorkDeliverable
    from cortexa.work import service as work_service

    _conv, row = await owned_artifact(db, conv_id, artifact_id)
    w = await work_service.get_work(db, payload.work_id, True)
    work_service.allowed(w, "edit")
    path = store.resolve_path(row)
    if not path.is_file():
        raise HTTPException(404, "产出文件不存在")
    raw = await run_in_threadpool(path.read_bytes)
    excerpt = raw.decode("utf-8", errors="replace")[:2000]
    d = WorkDeliverable(
        id=uuid.uuid4(),
        workspace_id=w.workspace_id,
        work_id=w.id,
        type="text",
        content=excerpt,
        filename=row.filename,
        submitted_by=actor_required().user_id,
        metadata_json={"size": len(raw), "from_artifact": str(row.id), "artifact_title": row.title},
    )
    work_service.STORAGE.mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(work_service.blob_path(d.id).write_bytes, raw)
    db.add(d)
    await db.commit()
    return {"deliverable_id": str(d.id), "work_id": str(w.id), "notice": "已复制为工作交付物（独立副本）"}


class KnowledgeInput(BaseModel):
    knowledge_base_id: uuid.UUID


@router.post("/conversations/{conv_id}/artifacts/{artifact_id}/knowledge", status_code=201)
async def to_knowledge(conv_id: uuid.UUID, artifact_id: uuid.UUID, payload: KnowledgeInput,
                       background_tasks: BackgroundTasks, db=Depends(get_db)):
    from cortexa.api.knowledge import ingest_document
    from cortexa.db.models import KnowledgeBase

    _conv, row = await owned_artifact(db, conv_id, artifact_id)
    kb = await db.get(KnowledgeBase, payload.knowledge_base_id)
    if kb is None or kb.workspace_id != row.workspace_id:
        raise HTTPException(404, "目标知识库不存在或无权访问")
    key = str(kb.id)
    prior = (row.metadata_json or {}).get("knowledge", {})
    if key in prior:
        return {"document_id": prior[key], "existing": True}
    path = store.resolve_path(row)
    if not path.is_file():
        raise HTTPException(404, "产出文件不存在")
    raw = await run_in_threadpool(path.read_bytes)
    upload = UploadFile(
        file=io.BytesIO(raw),
        filename=row.filename or f"{row.title}.md",
        headers=Headers({"content-type": "text/markdown" if row.format == "markdown" else "text/plain"}),
    )
    doc = await ingest_document(kb.id, background_tasks, upload, db, commit=False)
    row.metadata_json = {**(row.metadata_json or {}), "knowledge": {**prior, key: str(doc.id)}}
    await db.commit()
    return {"document_id": str(doc.id), "knowledge_base_id": key}
