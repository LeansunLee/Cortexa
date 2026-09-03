"""Knowledge Base API."""

from __future__ import annotations

import uuid
import base64
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.api.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseDetailOut,
    DocumentCreate,
    DocumentOut,
)
from agentdevstu.db.models import KnowledgeBase, Document

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


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
) -> KnowledgeBase:
    query = (
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents))
        .where(KnowledgeBase.id == kb_id)
    )
    result = await db.execute(query)
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.post("", response_model=KnowledgeBaseOut, status_code=201)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> KnowledgeBase:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    agent_uuid = uuid.UUID(payload.agent_id) if payload.agent_id else None
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
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    await db.delete(kb)


@router.post("/{kb_id}/documents", response_model=DocumentOut, status_code=201)
async def create_document(
    kb_id: uuid.UUID,
    payload: DocumentCreate,
    db: AsyncSession = Depends(get_db),
) -> Document:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    doc = Document(
        knowledge_base_id=kb_id,
        name=payload.name,
        content=payload.content,
        metadata_json={"source": "api"},
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


@router.post("/{kb_id}/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile = FastAPIFile(...),
    db: AsyncSession = Depends(get_db),
) -> Document:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    raw = await file.read()
    # Try UTF-8 decode for text files, fallback to base64 for binary
    try:
        text_content = raw.decode("utf-8")
    except UnicodeDecodeError:
        text_content = base64.b64encode(raw).decode("ascii")
    file_size = len(raw)
    doc = Document(
        knowledge_base_id=kb_id,
        name=file.filename or "unnamed",
        content=text_content,
        metadata_json={
            "source": "upload",
            "filename": file.filename,
            "content_type": file.content_type or "application/octet-stream",
            "size": file_size,
            "encoding": "utf-8" if text_content == raw.decode("utf-8", errors="replace") else "base64",
        },
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    query = select(Document).where(
        Document.id == doc_id,
        Document.knowledge_base_id == kb_id,
    )
    result = await db.execute(query)
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
