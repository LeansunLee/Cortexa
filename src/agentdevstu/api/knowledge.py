"""Knowledge Base API."""

from __future__ import annotations

from agentdevstu.usage.context import usage_action, annotate_usage

import asyncio
import shutil
import tempfile
import zipfile
from pathlib import Path
import uuid
from typing import Literal
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, UploadFile, Form
from fastapi import File as FastAPIFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from agentdevstu.api.deps import get_current_workspace, get_db
from agentdevstu.api.schemas import (
    DocumentCreate,
    DocumentContentUpdate,
    DocumentOut,
    DocumentSummaryUpdate,
    DocumentValidityUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseDescriptionUpdate,
    KnowledgeBaseDetailOut,
    KnowledgeBaseOut,
    KnowledgeFolderOut,
    KnowledgeBaseStatusUpdate,
    NameUpdate,
)
from agentdevstu.data import document_preview as previews
from agentdevstu.data.doc_storage import (
    delete_document_content,
    make_summary,
    save_document_content,
)
from agentdevstu.db.models import Document, KnowledgeBase, KnowledgeFolder
from agentdevstu.security.access import actor_required
from agentdevstu.data.document_jobs import document_job_lock

# Track active PDF extraction jobs to prevent duplicate processing
_active_pdf_jobs: set = set()
_recovery_task = None

async def knowledge_scope(request: Request, db: AsyncSession = Depends(get_db),
                          workspace_id: str | None = Depends(get_current_workspace)):
    """Apply the same workspace check to every knowledge route."""
    kb_id = request.path_params.get("kb_id")
    if not workspace_id:
        raise HTTPException(400, "workspace_id is required")
    if kb_id:
        try:
            await _workspace_kb(uuid.UUID(str(kb_id)), db, workspace_id)
        except ValueError:
            raise HTTPException(422, "知识库 ID 格式不正确") from None


router = APIRouter(prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(knowledge_scope)])


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    scope: str | None = None,
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[KnowledgeBase]:
    """List knowledge bases with optional scope filtering.
    scope=workspace -> only workspace KBs (agent_id is null)
    scope=agent -> only agent KBs (agent_id is not null)
    agent_id=xxx -> only KBs for that specific agent
    """
    query = select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
    if workspace_id:
        query = query.where(KnowledgeBase.workspace_id == uuid.UUID(workspace_id))
    if scope == "workspace":
        query = query.where(KnowledgeBase.agent_id.is_(None))
    elif scope == "agent":
        query = query.where(KnowledgeBase.agent_id.isnot(None))
    if agent_id:
        query = query.where(KnowledgeBase.agent_id == uuid.UUID(agent_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{kb_id}", response_model=KnowledgeBaseDetailOut)
async def get_knowledge_base(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> KnowledgeBase:
    query = (
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents), selectinload(KnowledgeBase.folders))
        .where(KnowledgeBase.id == kb_id)
    )
    if workspace_id:
        query = query.where(KnowledgeBase.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


def _can_manage():
    actor = actor_required()
    return actor.has("knowledge.manage") or actor.operations_knowledge_id is not None


async def _folder_in_kb(kb_id, folder_id, db):
    if folder_id is None:
        return None
    folder = await db.scalar(select(KnowledgeFolder).where(KnowledgeFolder.id == folder_id, KnowledgeFolder.knowledge_base_id == kb_id))
    if not folder:
        raise HTTPException(404, "目标文件夹不存在或不属于此知识库")
    return folder


def _can_edit_document(doc):
    actor = actor_required()
    return (actor.has("knowledge.manage")
            or actor.operations_knowledge_id == doc.knowledge_base_id
            or (actor.has("knowledge.use") and doc.created_by == actor.user_id))

def _require_knowledge_use_or_manage():
    actor = actor_required()
    if not (_can_manage() or actor.has("knowledge.use")):
        raise HTTPException(403, "没有使用知识库权限")


async def _ensure_document_name_available(kb_id, name, db, *, folder_id=None, exclude_id=None):
    query = select(Document.name).where(Document.knowledge_base_id == kb_id, Document.folder_id == folder_id)
    if exclude_id:
        query = query.where(Document.id != exclude_id)
    names = (await db.execute(query)).scalars().all()
    if any(doc_name.casefold() == name.casefold() for doc_name in names):
        raise HTTPException(409, "当前文件夹中已存在同名文件")


def _valid_folder_name(name):
    name = name.strip()
    if not name or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name):
        raise HTTPException(400, "文件夹名称不能为空或包含路径分隔符、控制字符")
    return name


@router.get("/{kb_id}/folders", response_model=list[KnowledgeFolderOut])
async def list_folders(kb_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    folders = (await db.execute(select(KnowledgeFolder).where(KnowledgeFolder.knowledge_base_id == kb_id).order_by(KnowledgeFolder.name))).scalars().all()
    return folders


class FolderCreate(BaseModel):
    name: str = Field(max_length=200)
    parent_id: uuid.UUID | None = None


class FolderMove(BaseModel):
    parent_id: uuid.UUID | None = None


@router.post("/{kb_id}/folders", status_code=201)
async def create_folder(kb_id: uuid.UUID, payload: FolderCreate, db: AsyncSession = Depends(get_db)):
    await _workspace_kb(kb_id, db, str(actor_required().workspace_id))
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以维护文件夹")
    parent = await _folder_in_kb(kb_id, payload.parent_id, db)
    folder = KnowledgeFolder(knowledge_base_id=kb_id, parent_id=parent.id if parent else None, name=_valid_folder_name(payload.name), created_by=actor_required().user_id)
    db.add(folder)
    try: await db.commit()
    except Exception:
        await db.rollback(); raise HTTPException(409, "同级文件夹名称已存在") from None
    await db.refresh(folder)
    return folder


@router.patch("/{kb_id}/folders/{folder_id}/move")
async def move_folder(kb_id: uuid.UUID, folder_id: uuid.UUID, payload: FolderMove, db: AsyncSession = Depends(get_db)):
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以维护文件夹")
    folder = await _folder_in_kb(kb_id, folder_id, db)
    parent = await _folder_in_kb(kb_id, payload.parent_id, db)
    if parent and parent.id == folder.id:
        raise HTTPException(409, "不能将文件夹移动到自身或子目录")
    if parent:
        descendants = {folder.id}
        pending = [folder.id]
        while pending:
            children = list((await db.execute(select(KnowledgeFolder.id).where(KnowledgeFolder.parent_id.in_(pending)))).scalars())
            pending = [item for item in children if item not in descendants]
            descendants.update(pending)
        if parent.id in descendants:
            raise HTTPException(409, "不能将文件夹移动到自身或子目录")
    folder.parent_id = parent.id if parent else None
    try: await db.commit()
    except Exception:
        await db.rollback(); raise HTTPException(409, "同级文件夹名称已存在") from None
    await db.refresh(folder)
    return folder


@router.patch("/{kb_id}/folders/{folder_id}")
async def rename_folder(kb_id: uuid.UUID, folder_id: uuid.UUID, payload: NameUpdate, db: AsyncSession = Depends(get_db)):
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以维护文件夹")
    folder = await _folder_in_kb(kb_id, folder_id, db)
    folder.name = _valid_folder_name(payload.name)
    try: await db.commit()
    except Exception:
        await db.rollback(); raise HTTPException(409, "同级文件夹名称已存在") from None
    return folder


@router.delete("/{kb_id}/folders/{folder_id}", status_code=204)
async def delete_folder(kb_id: uuid.UUID, folder_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以维护文件夹")
    folder = await _folder_in_kb(kb_id, folder_id, db)
    has_child = await db.scalar(select(KnowledgeFolder.id).where(KnowledgeFolder.parent_id == folder_id).limit(1))
    has_doc = await db.scalar(select(Document.id).where(Document.folder_id == folder_id).limit(1))
    if has_child or has_doc: raise HTTPException(409, "文件夹不为空，请先移动其中的内容")
    await db.delete(folder); await db.commit()


class MoveDocuments(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    folder_id: uuid.UUID | None = None


class BatchResourceAction(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    folder_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class MoveResources(BatchResourceAction):
    folder_id: uuid.UUID | None = None


def _validate_resource_count(payload: BatchResourceAction):
    count = len(set(payload.document_ids)) + len(set(payload.folder_ids))
    if count < 1:
        raise HTTPException(422, "请至少选择一个文件或文件夹")
    if count > 500:
        raise HTTPException(422, "每次最多操作 500 个项目")


def _top_level_selected_folder_ids(folder_ids: set[uuid.UUID], folder_map: dict[uuid.UUID, KnowledgeFolder]) -> set[uuid.UUID]:
    """Keep selected folders whose selected ancestors will not move them already."""
    top_level_ids: set[uuid.UUID] = set()
    for folder_id in folder_ids:
        ancestor_id = folder_map.get(folder_id).parent_id if folder_map.get(folder_id) else None
        while ancestor_id and ancestor_id not in folder_ids:
            ancestor = folder_map.get(ancestor_id)
            ancestor_id = ancestor.parent_id if ancestor else None
        if ancestor_id is None:
            top_level_ids.add(folder_id)
    return top_level_ids


@router.post("/{kb_id}/documents/move")
async def move_documents(kb_id: uuid.UUID, payload: MoveDocuments, db: AsyncSession = Depends(get_db)):
    folder = await _folder_in_kb(kb_id, payload.folder_id, db)
    actor = actor_required()
    docs = list((await db.execute(select(Document).where(Document.knowledge_base_id == kb_id, Document.id.in_(set(payload.document_ids))))).scalars().all())
    if len(docs) != len(set(payload.document_ids)): raise HTTPException(409, "部分文档不存在，请刷新后重试")
    if any(not _can_edit_document(d) for d in docs): raise HTTPException(403, "只能移动自己上传的文件")
    await db.execute(Document.__table__.update().where(Document.id.in_([d.id for d in docs])).values(folder_id=folder.id if folder else None))
    await db.commit()
    return {"moved_ids": [str(d.id) for d in docs], "folder_id": str(folder.id) if folder else None}


@router.post("/{kb_id}/resources/move")
async def move_resources(kb_id: uuid.UUID, payload: MoveResources, db: AsyncSession = Depends(get_db)):
    _validate_resource_count(payload)
    target = await _folder_in_kb(kb_id, payload.folder_id, db)
    document_ids = set(payload.document_ids)
    folder_ids = set(payload.folder_ids)
    actor = actor_required()

    docs = list((await db.execute(select(Document).where(
        Document.knowledge_base_id == kb_id,
        Document.id.in_(document_ids),
    ))).scalars().all()) if document_ids else []
    selected_folders = list((await db.execute(select(KnowledgeFolder).where(
        KnowledgeFolder.knowledge_base_id == kb_id,
        KnowledgeFolder.id.in_(folder_ids),
    ))).scalars().all()) if folder_ids else []
    if len(docs) != len(document_ids) or len(selected_folders) != len(folder_ids):
        raise HTTPException(409, "部分文件或文件夹不存在，请刷新后重试")
    if any(not _can_edit_document(doc) for doc in docs):
        raise HTTPException(403, "只能移动自己上传的文件")
    if folder_ids and not _can_manage():
        raise HTTPException(403, "只有知识库管理员可以移动文件夹")

    all_folders = list((await db.execute(select(KnowledgeFolder).where(
        KnowledgeFolder.knowledge_base_id == kb_id,
    ))).scalars().all())
    folder_map = {folder.id: folder for folder in all_folders}
    ancestor_id = target.id if target else None
    while ancestor_id:
        if ancestor_id in folder_ids:
            raise HTTPException(409, "不能将文件夹移动到自身或子目录")
        ancestor_id = folder_map.get(ancestor_id).parent_id if folder_map.get(ancestor_id) else None

    top_level_folder_ids = _top_level_selected_folder_ids(folder_ids, folder_map)
    top_level_folders = [folder for folder in selected_folders if folder.id in top_level_folder_ids]
    target_id = target.id if target else None
    selected_folder_names = {folder.name.casefold() for folder in top_level_folders}
    occupied_folder_names = {
        folder.name.casefold() for folder in all_folders
        if (folder.parent_id or None) == target_id and folder.id not in top_level_folder_ids
    }
    if selected_folder_names & occupied_folder_names:
        raise HTTPException(409, "目标位置已存在同名文件夹")

    if docs:
        occupied_doc_names = {
            name.casefold() for name in (await db.execute(select(Document.name).where(
                Document.knowledge_base_id == kb_id,
                Document.folder_id == target_id,
                Document.id.notin_(document_ids),
            ))).scalars().all()
        }
        if any(doc.name.casefold() in occupied_doc_names for doc in docs):
            raise HTTPException(409, "目标位置已存在同名文件")

    if document_ids:
        await db.execute(Document.__table__.update().where(Document.id.in_(document_ids)).values(folder_id=target_id))
    for folder in top_level_folders:
        folder.parent_id = target_id
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, "目标位置存在同名项目，请刷新后重试") from None
    return {
        "moved_document_ids": [str(item) for item in document_ids],
        "moved_folder_ids": [str(item) for item in top_level_folder_ids],
        "folder_id": str(target_id) if target_id else None,
    }


@router.post("/{kb_id}/resources/batch-delete")
async def batch_delete_resources(kb_id: uuid.UUID, payload: BatchResourceAction, db: AsyncSession = Depends(get_db)):
    _validate_resource_count(payload)
    document_ids = set(payload.document_ids)
    folder_ids = set(payload.folder_ids)
    docs = list((await db.execute(select(Document).where(
        Document.knowledge_base_id == kb_id,
        Document.id.in_(document_ids),
    ))).scalars().all()) if document_ids else []
    selected_folders = list((await db.execute(select(KnowledgeFolder).where(
        KnowledgeFolder.knowledge_base_id == kb_id,
        KnowledgeFolder.id.in_(folder_ids),
    ))).scalars().all()) if folder_ids else []
    if len(docs) != len(document_ids) or len(selected_folders) != len(folder_ids):
        raise HTTPException(409, "部分文件或文件夹不存在，请刷新后重试")
    if any(not _can_edit_document(doc) for doc in docs):
        raise HTTPException(403, "只能删除自己上传的文件")
    if folder_ids and not _can_manage():
        raise HTTPException(403, "只有知识库管理员可以删除文件夹")
    if folder_ids:
        has_child = await db.scalar(select(KnowledgeFolder.id).where(KnowledgeFolder.parent_id.in_(folder_ids)).limit(1))
        has_doc = await db.scalar(select(Document.id).where(Document.folder_id.in_(folder_ids)).limit(1))
        if has_child or has_doc:
            raise HTTPException(409, "所选文件夹中包含非空文件夹，请先移出其中的文件或子文件夹")

    for doc in docs:
        await db.delete(doc)
    for folder in selected_folders:
        await db.delete(folder)
    await db.commit()
    for doc_id in document_ids:
        await run_in_threadpool(delete_document_content, str(doc_id))
    return {
        "deleted_document_ids": [str(item) for item in document_ids],
        "deleted_folder_ids": [str(item) for item in folder_ids],
    }


@router.post("", response_model=KnowledgeBaseOut, status_code=201)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> KnowledgeBase:
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以管理知识库")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    agent_uuid = uuid.UUID(payload.agent_id) if payload.agent_id else None
    if agent_uuid:
        from agentdevstu.db.models import Agent
        agent = await db.get(Agent, agent_uuid)
        if not agent or str(agent.workspace_id) != workspace_id:
            raise HTTPException(404, "当前工作空间中未找到该 Agent")
    kb = KnowledgeBase(
        workspace_id=uuid.UUID(workspace_id),
        agent_id=agent_uuid,
        name=payload.name,
        description=payload.description,
        type=payload.type,
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以管理知识库")
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    # Delete associated documents first (avoid FK constraint error)
    from sqlalchemy import select as sa_select

    from agentdevstu.db.models import Document
    docs_result = await db.execute(sa_select(Document).where(Document.knowledge_base_id == kb_id))
    docs = list(docs_result.scalars().all())
    ids = [str(doc.id) for doc in docs]
    for doc in docs:
        await db.delete(doc)
    await db.delete(kb)
    await db.commit()
    for doc_id in ids:
        await run_in_threadpool(delete_document_content, doc_id)


@router.patch("/{kb_id}/name", response_model=KnowledgeBaseOut)
async def rename_knowledge_base(kb_id: uuid.UUID, payload: NameUpdate, db: AsyncSession = Depends(get_db)) -> KnowledgeBase:
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以管理知识库")
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    name = payload.name.strip()
    if not name or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name):
        raise HTTPException(400, "名称不能为空或包含路径分隔符、控制字符")
    kb.name = name
    await db.commit()
    await db.refresh(kb)
    return kb


@router.patch("/{kb_id}/description", response_model=KnowledgeBaseOut)
async def update_knowledge_base_description(kb_id: uuid.UUID, payload: KnowledgeBaseDescriptionUpdate, db: AsyncSession = Depends(get_db)) -> KnowledgeBase:
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以管理知识库")
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    kb.description = (payload.description or "").strip() or None
    await db.commit()
    await db.refresh(kb)
    return kb


@router.patch("/{kb_id}/status", response_model=KnowledgeBaseOut)
async def update_knowledge_base_status(
    kb_id: uuid.UUID,
    payload: KnowledgeBaseStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBase:
    """Enable or disable a knowledge base without changing its documents."""
    if not _can_manage(): raise HTTPException(403, "只有知识库管理员可以管理知识库")
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    kb.status = payload.status
    await db.commit()
    await db.refresh(kb)
    return kb


@router.post("/{kb_id}/documents", response_model=DocumentOut, status_code=201)
async def create_document(
    kb_id: uuid.UUID,
    payload: DocumentCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Document:
    """Create a plain-text document; the summary follows the 1000-char rule."""
    from agentdevstu.rag.summary import SUMMARY_FULL_TEXT_MAX_CHARS
    _require_knowledge_use_or_manage()

    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    text = payload.content
    if not text.strip():
        raise HTTPException(status_code=400, detail="内容不能为空")
    name = payload.name.strip()
    if not name or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name):
        raise HTTPException(400, "文件名不能为空或包含路径分隔符、控制字符")
    if not Path(name).suffix:
        name += '.txt'
    if Path(name).suffix.lower() not in {'.txt', '.md'}:
        raise HTTPException(400, "创建文本仅支持 md、txt 文件")
    await _folder_in_kb(kb_id, payload.folder_id, db)
    await _ensure_document_name_available(kb_id, name, db, folder_id=payload.folder_id)
    if len(text) <= SUMMARY_FULL_TEXT_MAX_CHARS:
        summary, source = text, "full"
    else:
        # Interim truncation; the background task upgrades it to an LLM summary.
        summary, source = make_summary(text), "truncated"
    doc = Document(
        knowledge_base_id=kb_id,
        folder_id=payload.folder_id,
        created_by=actor_required().user_id,
        name=name,
        content=summary,
        metadata_json={"source": "api", "summary_source": source, "summary_status": "pending" if source == "truncated" else "ready",
                       "index_status": "pending", "content_type": "text/plain", "encoding": "utf-8",
                       "has_full_content": True, "size": len(text.encode('utf-8'))},
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    # Commit before background workers open their independent sessions.
    try:
        await run_in_threadpool(save_document_content, str(doc.id), text)
        await db.commit()
    except Exception:
        await db.rollback()
        await run_in_threadpool(delete_document_content, str(doc.id))
        raise HTTPException(status_code=500, detail="文件保存失败，请重试") from None
    background_tasks.add_task(_safe_index, doc.id, kb_id)
    if source == "truncated":
        background_tasks.add_task(_summarize_document, doc.id)
    return doc


def _extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        return previews.extract_pdf_text(raw_bytes)
    except Exception:
        return ""


@router.post("/{kb_id}/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = FastAPIFile(...),
    folder_id: uuid.UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Document:
    _require_knowledge_use_or_manage()
    return await ingest_document(kb_id, background_tasks, file, db, folder_id=folder_id)


async def ingest_document(kb_id, background_tasks, file, db, *, commit=True, folder_id=None):
    """Shared upload pipeline; Work can include ingestion in its own transaction."""
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    await _folder_in_kb(kb_id, folder_id, db)
    raw = await file.read(previews.MAX_UPLOAD_SIZE + 1)
    if len(raw) > previews.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="单个文件不能超过 500 MB")
    if not raw:
        raise HTTPException(status_code=400, detail="不能上传空文件")
    kind = previews.file_kind(file.filename or "", {"content_type": file.content_type or ""})
    needs_extraction = kind != 'text'

    # Recognition runs only after the original has been durably saved.
    if needs_extraction:
        text_content = ""
        encoding = "utf-8"
    else:
        text_content = previews.decode_text(raw)
        encoding = 'utf-8'
    file_size = len(raw)
    await _ensure_document_name_available(kb_id, file.filename or "unnamed", db, folder_id=folder_id)
    doc = Document(
        knowledge_base_id=kb_id,
        folder_id=folder_id,
        created_by=actor_required().user_id,
        name=file.filename or "unnamed",
        content=make_summary(text_content),
        metadata_json={
            "source": "upload",
            "filename": file.filename,
            "content_type": file.content_type or "application/octet-stream",
            "size": file_size,
            "encoding": encoding,
            "has_full_content": True,
            "has_original": True,
            "index_status": "pending",
            "summary_status": "pending",
            **({"extraction_status": "pending"} if needs_extraction else {}),
        },
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    # Saving the original is required: extracted text cannot reproduce PDF/Office layout.
    try:
        await run_in_threadpool(previews.save_original, str(doc.id), raw)
        await run_in_threadpool(save_document_content, str(doc.id), text_content)
        if commit:
            await db.commit()
    except Exception:
        await db.rollback()
        await run_in_threadpool(delete_document_content, str(doc.id))
        raise HTTPException(status_code=500, detail="文件保存失败，请重试") from None
    if needs_extraction:
        background_tasks.add_task(_process_pdf, doc.id, kb_id)
    else:
        background_tasks.add_task(_safe_index, doc.id, kb_id)
        background_tasks.add_task(_summarize_document, doc.id)

    return doc


async def _summarize_document(document_id) -> None:
    async with document_job_lock(document_id, 'summary'):
        await _summarize_document_impl(document_id)


@usage_action("document_summary", source="knowledge", background=True)
async def _summarize_document_impl(document_id) -> None:
    """Replace the DB truncation summary with an LLM summary.

    Full text stays on the filesystem; the summary only upgrades the
    retrieval signal stored in ``Document.content``.
    """
    from agentdevstu.data.doc_storage import load_document_content
    from agentdevstu.db.engine import async_session_factory
    from agentdevstu.rag.summary import generate_document_summary

    try:
        async with async_session_factory() as session:
            doc = await session.get(Document, document_id)
            if not doc:
                return
            content = await run_in_threadpool(load_document_content, str(document_id))
            if content is None:
                content = doc.content or ""
            if not content.strip() or (doc.metadata_json or {}).get("encoding") == "base64":
                return
            revision = (doc.metadata_json or {}).get('summary_revision')
            if (doc.metadata_json or {}).get('summary_source') == 'manual':
                return
            doc.metadata_json = {**(doc.metadata_json or {}), 'summary_status': 'processing'}
            await session.commit()
            _usage_kb = await session.get(KnowledgeBase, doc.knowledge_base_id)
            annotate_usage(object_type="document", object_id=doc.id, workspace_id=getattr(_usage_kb, "workspace_id", None))
            summary, source = (content, 'file_info') if (doc.metadata_json or {}).get('summary_scope') == 'file_info' else await generate_document_summary(doc.name, content)
            await session.refresh(doc, with_for_update=True)
            latest = await run_in_threadpool(load_document_content, str(document_id))
            if latest != content or (doc.metadata_json or {}).get('summary_revision') != revision:
                return
            doc.content = summary
            doc.metadata_json = {**(doc.metadata_json or {}), "summary_source": source,
                                 'summary_status': 'error' if source == 'truncated' else 'ready',
                                 'summary_error': 'LLM 未返回有效摘要，已保留截断文本，可重试' if source == 'truncated' else None,
                                 'summarized_at': datetime.now(timezone.utc).isoformat()}
            await session.commit()
            print(f"[DOC_SUMMARY] Updated summary for {document_id} (source={source})", flush=True)
    except Exception as error:
        print(f"[DOC_SUMMARY] Background summary failed for {document_id}: {type(error).__name__}: {error}", flush=True)
        async with async_session_factory() as session:
            doc = await session.get(Document, document_id)
            if doc and (doc.metadata_json or {}).get('summary_source') != 'manual':
                doc.metadata_json = {**(doc.metadata_json or {}), 'summary_status': 'error',
                                     'summary_error': str(error)[:200]}
                await session.commit()


async def _process_pdf(document_id, kb_id):
    # Retain the existing job/lock name for compatibility with running PDF jobs.
    if document_id in _active_pdf_jobs:
        return
    _active_pdf_jobs.add(document_id)
    try:
        async with document_job_lock(document_id, 'pdf'):
            from agentdevstu.db.engine import async_session_factory
            async with async_session_factory() as session:
                doc = await session.get(Document, document_id)
                if not doc or (doc.metadata_json or {}).get('extraction_status') == 'ready':
                    return
            await _process_pdf_impl(document_id, kb_id)
    finally:
        _active_pdf_jobs.discard(document_id)


async def recover_pdf_jobs() -> int:
    """Requeue interrupted PDF/image extraction after an application restart."""
    from agentdevstu.db.engine import async_session_factory
    from sqlalchemy import or_ as sa_or
    async with async_session_factory() as session:
        result = await session.execute(
            select(Document)
            .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
            .where(sa_or(
                Document.metadata_json["extraction_status"].as_string() == "pending",
                Document.metadata_json["extraction_status"].as_string() == "processing",
            ))
        )
        docs = list(result.scalars().all())
    for doc in docs:
        await _process_pdf(doc.id, doc.knowledge_base_id)
    # Text jobs also use durable pending markers; recovery is sequential to
    # avoid an OCR/LLM burst at startup.
    async with async_session_factory() as session:
        result = await session.execute(select(Document).where(Document.status == 'active'))
        remaining = list(result.scalars().all())
    for doc in remaining:
        metadata = doc.metadata_json or {}
        if metadata.get('extraction_status') in {'pending', 'processing', 'error'}:
            continue
        if metadata.get('index_status') in {'pending', 'processing'}:
            await _safe_index(doc.id, doc.knowledge_base_id)
        if metadata.get('summary_status') in {'pending', 'processing'}:
            await _summarize_document(doc.id)
    if docs:
        print(f"[PDF] Requeued {len(docs)} interrupted extraction jobs", flush=True)
    return len(docs)


@usage_action("document_summary", source="knowledge", background=True)
async def _process_pdf_impl(document_id, kb_id):
    from agentdevstu.db.engine import async_session_factory
    from agentdevstu.data.document_extraction import extract_document
    from agentdevstu.rag.summary import generate_document_summary
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if not doc:
            return
        try:
            revision = (doc.metadata_json or {}).get('summary_revision')
            doc.metadata_json = {**(doc.metadata_json or {}), 'extraction_status': 'processing', 'extraction_error': None,
                                 'extraction_started_at': datetime.now(timezone.utc).isoformat(),
                                 'extraction_attempts': (doc.metadata_json or {}).get('extraction_attempts', 0) + 1}
            await session.commit()
            original = await run_in_threadpool(previews.original_file, str(doc.id), doc.name, doc.metadata_json, doc.content or '')
            if not original:
                raise RuntimeError('原文件缺失，请重新上传')
            text, ocr_pages, information_only = await extract_document(str(doc.id), doc.name, doc.metadata_json or {}, original)
            if not text.strip():
                raise RuntimeError('文件没有可识别文字，请检查清晰度或手动填写摘要')
            await session.refresh(doc, with_for_update=True)
            await run_in_threadpool(save_document_content, str(doc.id), text)
            doc.metadata_json = {**(doc.metadata_json or {}), 'content_revision': str(uuid.uuid4()),
                                 'index_status': 'pending', 'summary_status': 'pending'}
            await session.commit()
            _usage_kb = await session.get(KnowledgeBase, doc.knowledge_base_id)
            annotate_usage(object_type="document", object_id=doc.id, workspace_id=getattr(_usage_kb, "workspace_id", None))
            summary, summary_source = (text, 'file_info') if information_only else await generate_document_summary(doc.name, text)
            await session.refresh(doc, with_for_update=True)
            if (doc.metadata_json or {}).get('summary_revision') == revision and (doc.metadata_json or {}).get('summary_source') != 'manual':
                doc.content = summary
            else:
                summary_source = (doc.metadata_json or {}).get('summary_source', 'manual')
            doc.metadata_json = {**doc.metadata_json, 'encoding': 'utf-8', 'has_full_content': True,
                                 'extraction_status': 'ready', 'ocr_pages': ocr_pages, 'extraction_error': None,
                                 'summary_scope': 'file_info' if information_only else 'content',
                                 'summary_source': summary_source, 'index_status': 'pending',
                                 'summary_status': 'error' if summary_source == 'truncated' else 'ready',
                                 'summary_error': 'LLM 摘要生成失败，可重试' if summary_source == 'truncated' else None,
                                 'extracted_at': datetime.now(timezone.utc).isoformat()}
            await session.commit()
        except Exception as error:
            await session.rollback()
            doc = await session.get(Document, document_id)
            if doc:
                doc.metadata_json = {**(doc.metadata_json or {}), 'extraction_status': 'error', 'extraction_error': str(error)[:200],
                                     'summary_status': 'ready' if (doc.metadata_json or {}).get('summary_source') == 'manual' else 'error',
                                     'index_status': 'error', 'index_error': '正文识别失败，请先重试识别'}
                await session.commit()
            return
    await _safe_index(document_id, kb_id)


@router.post("/{kb_id}/documents/{doc_id}/extract", status_code=202)
async def retry_pdf_extraction(kb_id: uuid.UUID, doc_id: uuid.UUID, background_tasks: BackgroundTasks,
                               db: AsyncSession = Depends(get_db),
                               workspace_id: str | None = Depends(get_current_workspace)):
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    if doc.id not in _active_pdf_jobs:
        metadata = doc.metadata_json or {}
        doc.metadata_json = {**metadata, 'extraction_status': 'pending', 'extraction_error': None,
                             'index_status': 'pending', 'index_error': None,
                             'summary_status': 'ready' if metadata.get('summary_source') == 'manual' else 'pending',
                             'summary_error': None}
        await db.commit()
        background_tasks.add_task(_process_pdf, doc.id, kb_id)
    return {'status': 'pending'}


async def _safe_index(document_id, kb_id):
    async with document_job_lock(document_id, 'index'):
        await _index_document_impl(document_id, kb_id)


async def _index_document_impl(document_id, kb_id):
    """Safely index a document, handling errors."""
    try:
        from agentdevstu.db.engine import async_session_factory
        from agentdevstu.rag.retriever import index_document
        async with async_session_factory() as new_db:
            doc = await new_db.get(Document, document_id)
            if not doc:
                return
            revision = (doc.metadata_json or {}).get('content_revision')
            doc.metadata_json = {**(doc.metadata_json or {}), 'index_status': 'processing', 'index_error': None}
            await new_db.commit()
            count = await index_document(new_db, document_id, kb_id)
            await new_db.refresh(doc, with_for_update=True)
            if (doc.metadata_json or {}).get('content_revision') != revision:
                await new_db.rollback()
                return
            doc.metadata_json = {**(doc.metadata_json or {}), 'index_status': 'ready' if count else 'unsupported',
                                 'index_chunks': count, 'indexed_at': datetime.now(timezone.utc).isoformat()}
            await new_db.commit()
            print(f"[RAG] Indexed {count} chunks for document {document_id}")
    except Exception as e:
        print(f"[RAG] Indexing failed for document {document_id}: {e}")
        async with async_session_factory() as session:
            doc = await session.get(Document, document_id)
            if doc:
                doc.metadata_json = {**(doc.metadata_json or {}), 'index_status': 'error', 'index_error': str(e)[:200]}
                await session.commit()


@router.patch("/{kb_id}/documents/{doc_id}/name", response_model=DocumentOut)
async def rename_document(kb_id: uuid.UUID, doc_id: uuid.UUID, payload: NameUpdate, db: AsyncSession = Depends(get_db)) -> Document:
    doc = await db.scalar(select(Document).where(Document.id == doc_id, Document.knowledge_base_id == kb_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    name = payload.name.strip()
    if not name or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name):
        raise HTTPException(400, "文件名不能为空或包含路径分隔符、控制字符")
    original_suffix = Path(doc.name).suffix
    if original_suffix and not Path(name).suffix:
        name += original_suffix
    await _ensure_document_name_available(kb_id, name, db, folder_id=doc.folder_id, exclude_id=doc.id)
    doc.name = name
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document from knowledge base."""
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _can_edit_document(doc): raise HTTPException(403, "只能删除自己上传的文件")
    await db.delete(doc)
    await db.commit()
    await run_in_threadpool(delete_document_content, str(doc_id))


@router.patch("/{kb_id}/documents/{doc_id}/validity", response_model=DocumentOut)
async def update_document_validity(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    payload: DocumentValidityUpdate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Document:
    """Set an inclusive expiry date; null keeps the document permanently valid."""
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    doc.valid_until = payload.valid_until
    await db.commit()
    await db.refresh(doc)
    return doc


@router.patch("/{kb_id}/documents/{doc_id}/summary", response_model=DocumentOut)
async def update_document_summary(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    payload: DocumentSummaryUpdate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Document:
    """Edit the retrieval summary stored in ``Document.content``.

    Manual edits are marked with ``summary_source="manual"`` so the UI can
    distinguish them from LLM-generated summaries.
    """
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="摘要不能为空")
    await db.refresh(doc, with_for_update=True)
    doc.content = content
    doc.metadata_json = {**(doc.metadata_json or {}), "summary_source": "manual", "summary_status": "ready",
                         "summary_revision": str(uuid.uuid4()), "summary_error": None}
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{kb_id}/documents/{doc_id}/content")
async def get_document_content(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> dict:
    """Return the editable full text of a plain-text document."""
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    if previews.file_kind(doc.name, doc.metadata_json or {}) != "text":
        raise HTTPException(status_code=400, detail="仅支持编辑纯文本文档（md/txt 等）")
    try:
        content = await run_in_threadpool(previews.text_content, str(doc_id), doc.name, doc.metadata_json or {}, doc.content or "")
    except previews.PreviewError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return {"doc_id": str(doc_id), "name": doc.name, "content": content}


@router.put("/{kb_id}/documents/{doc_id}/content", response_model=DocumentOut)
async def update_document_content(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    payload: DocumentContentUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Document:
    """Save edited full text; the stored summary follows the 1000-char rule."""
    from agentdevstu.data.doc_storage import save_document_content
    from agentdevstu.rag.summary import SUMMARY_FULL_TEXT_MAX_CHARS

    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    if previews.file_kind(doc.name, doc.metadata_json or {}) != "text":
        raise HTTPException(status_code=400, detail="仅支持编辑纯文本文档（md/txt 等）")
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="内容不能为空")
    text = payload.content
    if len(text.strip()) <= SUMMARY_FULL_TEXT_MAX_CHARS:
        summary, source = text, "full"
    else:
        # Interim truncation; the background task upgrades it to an LLM summary.
        summary, source = make_summary(text), "truncated"
    from agentdevstu.data.doc_storage import load_document_content
    await db.refresh(doc, with_for_update=True)
    previous = await run_in_threadpool(load_document_content, str(doc_id))
    try:
        await run_in_threadpool(save_document_content, str(doc_id), text)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="文件保存失败，请重试") from None
    doc.content = summary
    doc.metadata_json = {**(doc.metadata_json or {}), "summary_source": source,
                         "size": len(text.encode("utf-8")), "has_full_content": True,
                         "content_revision": str(uuid.uuid4()), "index_status": "pending",
                         "summary_revision": str(uuid.uuid4()),
                         "summary_status": "pending" if source == "truncated" else "ready", "summary_error": None}
    try:
        await db.commit()
    except Exception:
        # Restore while this transaction still owns the row lock.
        if previous is not None:
            await run_in_threadpool(save_document_content, str(doc_id), previous)
        await db.rollback()
        raise HTTPException(500, '文档保存失败，未提交索引任务') from None
    await db.refresh(doc)
    background_tasks.add_task(_safe_index, doc_id, kb_id)
    if source == "truncated":
        background_tasks.add_task(_summarize_document, doc_id)
    return doc


@router.post("/{kb_id}/documents/{doc_id}/regenerate-summary", response_model=DocumentOut)
@usage_action("document_summary", source="knowledge", background=False)
async def regenerate_document_summary(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Document:
    """Regenerate the stored summary from the full text on the filesystem."""
    from agentdevstu.data.doc_storage import load_document_content
    from agentdevstu.rag.summary import generate_document_summary

    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    metadata = doc.metadata_json or {}
    # Check extraction status before attempting summary generation
    extraction_status = metadata.get("extraction_status")
    if extraction_status in ("pending", "processing"):
        raise HTTPException(status_code=400, detail="文件文字识别正在处理中，请稍后重试")
    if extraction_status == "error":
        error_msg = metadata.get("extraction_error", "未知错误")
        raise HTTPException(status_code=400, detail=f"文件文字识别失败：{error_msg}，请先修复后再重新生成摘要")
    content = await run_in_threadpool(load_document_content, str(doc_id))
    if (not content or metadata.get('encoding') == 'base64') and previews.file_kind(doc.name, metadata) != 'text':
        # Legacy PDFs may have an original but no extracted content. Resume the
        # same extraction pipeline instead of trying to summarize an empty file.
        doc.metadata_json = {**metadata, 'extraction_status': 'pending'}
        await db.commit()
        await _process_pdf(doc.id, kb_id)
        await db.refresh(doc)
        metadata = doc.metadata_json or {}
        content = await run_in_threadpool(load_document_content, str(doc_id))
        if metadata.get('extraction_status') != 'ready':
            raise HTTPException(422, metadata.get('extraction_error') or '正文提取失败，请重试')
    if content is None and not metadata.get('has_full_content'):
        content = doc.content or ""
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="文档正文为空，无法生成摘要。请确保文字识别已完成")
    revision = metadata.get('summary_revision')
    _usage_kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
    annotate_usage(object_type="document", object_id=doc.id, workspace_id=getattr(_usage_kb, "workspace_id", None))
    summary, source = (content, 'file_info') if metadata.get('summary_scope') == 'file_info' else await generate_document_summary(doc.name, content)
    await db.refresh(doc, with_for_update=True)
    latest = await run_in_threadpool(load_document_content, str(doc_id))
    if (latest is not None and latest != content) or (doc.metadata_json or {}).get('summary_revision') != revision:
        raise HTTPException(409, "文档或摘要已被修改，请刷新后重试")
    if source == 'truncated':
        doc.metadata_json = {**(doc.metadata_json or {}), 'summary_status': 'error',
                             'summary_error': 'LLM 摘要生成失败，原摘要已保留'}
        await db.commit()
        raise HTTPException(502, "LLM 摘要生成失败，原摘要已保留，请重试")
    doc.content = summary
    doc.metadata_json = {**(doc.metadata_json or {}), "summary_source": source,
                         'summary_status': 'ready', 'summary_error': None,
                         'summary_revision': str(uuid.uuid4()),
                         'summarized_at': datetime.now(timezone.utc).isoformat()}
    await db.commit()
    await db.refresh(doc)
    return doc



async def _preview_document_record(kb_id, doc_id, db, workspace_id):
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    if workspace_id:
        kb = await db.get(KnowledgeBase, kb_id)
        if not kb or str(kb.workspace_id) != workspace_id:
            raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.get("/{kb_id}/documents/{doc_id}/preview")
async def preview_document(
    kb_id: uuid.UUID, doc_id: uuid.UUID,
    retry: bool = False,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    metadata = doc.metadata_json or {}
    if retry:
        (previews.document_dir(str(doc_id)) / 'preview-error.json').unlink(missing_ok=True)
    info = await run_in_threadpool(previews.preview_info, str(doc_id), doc.name, metadata, doc.content or '')
    if info['status'] == 'processing':
        previews.start_office_preview(str(doc_id), doc.name)
    return {
        'doc_id': str(doc_id), 'name': doc.name, 'size': metadata.get('size', 0),
        'content_type': metadata.get('content_type', 'text/plain'), **info,
    }


@router.get("/{kb_id}/documents/{doc_id}/pages/{page}")
async def preview_document_page(
    kb_id: uuid.UUID, doc_id: uuid.UUID, page: int,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    if page < 1:
        raise HTTPException(status_code=404, detail="页码超出范围")
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    metadata = doc.metadata_json or {}
    info = await run_in_threadpool(previews.preview_info, str(doc_id), doc.name, metadata, doc.content or '')
    if info['status'] != 'ready':
        raise HTTPException(status_code=409, detail=info['message'] or '预览尚未就绪')
    if page > info['page_count']:
        raise HTTPException(status_code=404, detail="页码超出范围")
    if info['kind'] == 'text':
        content = await run_in_threadpool(previews.text_content, str(doc_id), doc.name, metadata, doc.content or '')
        start = (page - 1) * previews.TEXT_PAGE_SIZE
        return JSONResponse({'page': page, 'content': content[start:start + previews.TEXT_PAGE_SIZE]})
    try:
        path = await run_in_threadpool(previews.render_page, str(doc_id), info['kind'], page)
    except (IndexError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="文档或页面不存在") from None
    except Exception:
        raise HTTPException(status_code=422, detail="该页无法渲染，请下载原文件查看") from None
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, max-age=86400'})


@router.get("/{kb_id}/documents/{doc_id}/raw")
async def get_raw_document(
    kb_id: uuid.UUID, doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    path = await run_in_threadpool(previews.original_file, str(doc_id), doc.name, doc.metadata_json or {}, doc.content or '')
    if not path:
        raise HTTPException(status_code=404, detail="原文件缺失，请重新上传")
    return FileResponse(path, filename=doc.name, media_type='application/octet-stream',
                        headers={'X-Content-Type-Options': 'nosniff'})


@router.post("/{kb_id}/reindex", response_model=dict)
async def reindex_knowledge_base(
    kb_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> dict:
    """Re-index documents from full originals within the current workspace."""
    await _workspace_kb(kb_id, db, workspace_id)

    result = await db.execute(select(Document).where(Document.knowledge_base_id == kb_id))
    docs = list(result.scalars().all())
    for doc in docs:
        metadata = doc.metadata_json or {}
        if previews.file_kind(doc.name, metadata) != 'text' and metadata.get('extraction_status') != 'ready':
            doc.metadata_json = {**metadata, 'extraction_status': 'pending'}
            background_tasks.add_task(_process_pdf, doc.id, kb_id)
        else:
            doc.metadata_json = {**metadata, 'index_status': 'pending',
                                 'summary_status': 'ready' if metadata.get('summary_source') == 'manual' else 'pending'}
            background_tasks.add_task(_safe_index, doc.id, kb_id)
            background_tasks.add_task(_summarize_document, doc.id)
    await db.commit()
    return {'status': 'queued', 'total_docs': len(docs)}


@router.post("/{kb_id}/documents/{doc_id}/reindex", status_code=202)
async def reindex_single_document(kb_id: uuid.UUID, doc_id: uuid.UUID, background_tasks: BackgroundTasks,
                                  db: AsyncSession = Depends(get_db),
                                  workspace_id: str | None = Depends(get_current_workspace)):
    doc = await _preview_document_record(kb_id, doc_id, db, workspace_id)
    if not _can_edit_document(doc): raise HTTPException(403, "只能修改自己上传的文件")
    metadata = doc.metadata_json or {}
    if metadata.get('extraction_status') in {'pending', 'processing', 'error'}:
        raise HTTPException(409, '请先完成 文件正文识别')
    doc.metadata_json = {**metadata, 'index_status': 'pending', 'index_error': None}
    await db.commit()
    background_tasks.add_task(_safe_index, doc.id, kb_id)
    return {'status': 'queued'}


@router.post("/reprocess-pending-pdfs", response_model=dict)
async def reprocess_pending_pdfs(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> dict:
    """Re-process all pending PDF documents across all knowledge bases in the workspace."""
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    result = await db.execute(
        select(Document)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.workspace_id == uuid.UUID(workspace_id),
            Document.metadata_json["extraction_status"].as_string().in_(["pending", "processing", "error"])
        )
    )
    pending_docs = list(result.scalars().all())
    queued = 0
    counts = {state: sum((d.metadata_json or {}).get('extraction_status') == state for d in pending_docs)
              for state in ('pending', 'processing', 'error')}
    for doc in pending_docs:
        if doc.id not in _active_pdf_jobs:
            doc.metadata_json = {**(doc.metadata_json or {}), 'extraction_status': 'pending'}
            background_tasks.add_task(_process_pdf, doc.id, doc.knowledge_base_id)
            queued += 1
    await db.commit()

    return {'status': 'queued', 'pending_count': len(pending_docs), 'queued_count': queued, **counts}


# --- Advanced Retrieval Endpoints ---


class BatchDeleteDocuments(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class PushDocument(BaseModel):
    target_kb_id: uuid.UUID


async def _workspace_kb(kb_id, db, workspace_id):
    kb = await db.get(KnowledgeBase, kb_id)
    if not workspace_id or not kb or str(kb.workspace_id) != workspace_id:
        raise HTTPException(status_code=404, detail="当前工作空间中未找到该知识库")
    return kb


def _build_download_archive(docs, folders=None):
    """Build on disk, retain original bytes, and never allow paths in ZIP entries."""
    folders = folders or {}
    temporary = tempfile.TemporaryDirectory(prefix="knowledge-download-")
    try:
        archive = Path(temporary.name) / "documents.zip"
        used = set()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as output:
            for doc in docs:
                original = previews.original_file(str(doc.id), doc.name, doc.metadata_json or {}, doc.content or '')
                if not original:
                    raise HTTPException(status_code=409, detail=f"「{doc.name}」原文件缺失，请重新上传或取消勾选")
                name = (doc.name or "document").replace("\\", "/").split("/")[-1]
                name = ''.join(c for c in name if ord(c) >= 32 and c not in ':*?"<>|').strip(' .') or "document"
                stem, suffix = Path(name).stem, Path(name).suffix
                candidate, count = name, 2
                parts = []
                folder_id = getattr(doc, "folder_id", None)
                while folder_id:
                    folder = folders.get(folder_id)
                    if not folder: break
                    clean = ''.join(c for c in (folder.name or "folder") if ord(c) >= 32 and c not in ':*?"<>|').strip(' .') or "folder"
                    parts.append(clean)
                    folder_id = folder.parent_id
                prefix = '/'.join(reversed(parts))
                candidate = f"{prefix}/{candidate}" if prefix else candidate
                prefix = f"{prefix}/" if prefix else ""
                while candidate.casefold() in used:
                    candidate = prefix + f"{stem} ({count}){suffix}"
                    count += 1
                used.add(candidate.casefold())
                output.write(original, arcname=candidate)
        return temporary, archive
    except BaseException:
        temporary.cleanup()
        raise


@router.post("/{kb_id}/documents/batch-download")
async def batch_download_documents(
    kb_id: uuid.UUID, payload: BatchDeleteDocuments,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    await _workspace_kb(kb_id, db, workspace_id)
    ids = list(dict.fromkeys(payload.document_ids))
    result = await db.execute(select(Document).options(selectinload(Document.folder)).where(Document.knowledge_base_id == kb_id, Document.id.in_(ids)))
    docs = {doc.id: doc for doc in result.scalars().all()}
    if len(docs) != len(ids):
        raise HTTPException(status_code=409, detail="部分文档已被删除或不属于此知识库，请刷新后重新选择")
    if not (_can_manage() or actor_required().has("knowledge.use")):
        raise HTTPException(status_code=403, detail="没有使用知识库权限")
    folder_rows = (await db.execute(select(KnowledgeFolder).where(KnowledgeFolder.knowledge_base_id == kb_id))).scalars().all()
    folder_map = {folder.id: folder for folder in folder_rows}
    temporary, archive = await run_in_threadpool(_build_download_archive, [docs[ident] for ident in ids], folder_map)
    return FileResponse(archive, filename="知识库文档.zip", media_type="application/zip",
                        background=BackgroundTask(temporary.cleanup),
                        headers={"X-Content-Type-Options": "nosniff"})


@router.post("/{kb_id}/documents/batch-delete")
async def batch_delete_documents(
    kb_id: uuid.UUID, payload: BatchDeleteDocuments,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    await _workspace_kb(kb_id, db, workspace_id)
    ids = set(payload.document_ids)
    result = await db.execute(select(Document).where(Document.knowledge_base_id == kb_id, Document.id.in_(ids)))
    docs = list(result.scalars().all())
    if len(docs) != len(ids):
        raise HTTPException(status_code=409, detail="部分文档已被删除或不属于此知识库，请刷新后重新选择")
    if any(not _can_edit_document(doc) for doc in docs):
        raise HTTPException(status_code=403, detail="只能删除自己上传的文件")
    for doc in docs:
        await db.delete(doc)
    await db.commit()
    # Only remove files after the database transaction succeeds.
    for doc_id in ids:
        await run_in_threadpool(delete_document_content, str(doc_id))
    return {"deleted_ids": [str(doc_id) for doc_id in ids], "deleted_count": len(ids)}


def _copy_document_files(source, destination_id):
    source_id = str(source.id)
    target = previews.document_dir(destination_id)
    target.mkdir(parents=True, exist_ok=False)
    original = previews.original_file(source_id, source.name, source.metadata_json or {}, source.content or '')
    if original:
        shutil.copyfile(original, target / 'original')
    content = previews.load_document_content(source_id)
    save_document_content(destination_id, content if content is not None else source.content or '')
    return original is not None


@router.post("/{kb_id}/documents/{doc_id}/push", response_model=DocumentOut, status_code=201)
async def push_document_to_workspace(
    kb_id: uuid.UUID, doc_id: uuid.UUID, payload: PushDocument,
    response: Response, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    source_kb = await _workspace_kb(kb_id, db, workspace_id)
    if not (actor_required().has("knowledge.manage") or actor_required().has("knowledge.use")):
        raise HTTPException(403, "推送到公共库需要知识库使用权限")
    if not source_kb.agent_id:
        raise HTTPException(status_code=400, detail="只能从 Agent 独立知识库推送文档")
    source = await db.get(Document, doc_id)
    if not source or source.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="源文档不存在")
    if not _can_edit_document(source):
        raise HTTPException(status_code=403, detail="只能推送自己上传的文件")
    # Serialize pushes to the same target so retries/double clicks cannot create duplicates.
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == payload.target_kb_id).with_for_update())
    target = result.scalar_one_or_none()
    if not target or target.workspace_id != source_kb.workspace_id or target.agent_id:
        raise HTTPException(status_code=400, detail="目标必须是当前工作空间的公共知识库")
    result = await db.execute(select(Document).where(
        Document.knowledge_base_id == target.id,
        Document.metadata_json['pushed_from_document_id'].as_string() == str(doc_id),
    ))
    existing = result.scalars().first()
    if existing:
        response.status_code = 200
        return existing
    new_id = uuid.uuid4()
    copied = Document(
        id=new_id, knowledge_base_id=target.id, name=source.name,
        content=source.content or '',
        valid_until=getattr(source, 'valid_until', None),
        metadata_json={**(source.metadata_json or {}), 'pushed_from_document_id': str(doc_id),
                       'pushed_from_kb_id': str(kb_id), 'pushed_from_agent_id': str(source_kb.agent_id)},
    )
    try:
        has_original = await run_in_threadpool(_copy_document_files, source, str(new_id))
        copied.metadata_json = {**copied.metadata_json, 'has_original': has_original, 'has_full_content': True,
                                'index_status': 'pending'}
        db.add(copied)
        await db.flush()
        await db.refresh(copied)
        await db.commit()
    except Exception:
        await db.rollback()
        await run_in_threadpool(delete_document_content, str(new_id))
        raise HTTPException(status_code=500, detail="推送失败，原文档已保留，请重试") from None
    background_tasks.add_task(_safe_index, new_id, payload.target_kb_id)
    return copied


class SearchRequest(BaseModel):
    """Request body for knowledge base search."""
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.1, ge=0, le=1000)
    strategy: Literal['bm25', 'hyde', 'multi_query', 'ensemble', 'parent_child'] = 'bm25'
    # HyDE specific
    hyde_prompt_template: str | None = None
    # Multi-Query specific
    num_query_variants: int = Field(default=3, ge=1, le=10)
    rrf_k: int = Field(default=60, ge=1, le=500)
    # Parent-Child specific
    use_parent_context: bool = True


class SearchResult(BaseModel):
    """Single search result."""
    chunk_id: str
    document_id: str
    document_name: str
    content: str
    score: float
    metadata: dict | None = None


class SearchResponse(BaseModel):
    """Search response with results and metadata."""
    results: list[SearchResult]
    strategy: str
    total: int
    query: str
    matched_count: int | None = None
    selected_count: int = 0
    truncated: bool | None = None


@router.post("/{kb_id}/search", response_model=SearchResponse)
async def search_knowledge_base(
    kb_id: uuid.UUID,
    payload: SearchRequest,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> SearchResponse:
    """Search a knowledge base with configurable retrieval strategy.

    Strategies:
    - bm25: BM25 keyword search (default, fast)
    - hyde: Hypothetical Document Embeddings (better for fuzzy queries)
    - multi_query: Multiple query variants + RRF fusion (better recall)
    - ensemble: BM25 + vector hybrid search
    - parent_child: Small-chunk retrieval with parent context
    """
    # Verify knowledge base exists
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or (workspace_id and str(kb.workspace_id) != workspace_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.status != "active":
        raise HTTPException(status_code=409, detail="知识库已禁用，请先启用后再搜索")

    from agentdevstu.rag.retriever import RetrievalConfig, retrieve_relevant_chunks

    config = RetrievalConfig(
        strategy=payload.strategy,
        top_k=payload.top_k,
        min_score=payload.min_score,
        hyde_prompt_template=payload.hyde_prompt_template,
        num_query_variants=payload.num_query_variants,
        rrf_k=payload.rrf_k,
        use_parent_context=payload.use_parent_context,
    )

    results = await retrieve_relevant_chunks(
        db=db,
        knowledge_base_ids=[str(kb_id)],
        query_text=payload.query,
        top_k=payload.top_k,
        min_score=payload.min_score,
        strategy=payload.strategy,
        config=config,
    )

    return SearchResponse(
        results=[
            SearchResult(
                chunk_id=str(r.chunk_id),
                document_id=str(r.document_id),
                document_name=r.document_name,
                content=r.content,
                score=r.score,
                metadata=r.metadata,
            )
            for r in results
        ],
        strategy=payload.strategy,
        total=len(results),
        query=payload.query,
        matched_count=(results[0].metadata or {}).get('matched_count') if results else 0,
        selected_count=len(results),
        truncated=(results[0].metadata or {}).get('truncated') if results else False,
    )
