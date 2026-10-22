"""对话产出物：模型通过 save_document 工具落盘的文档，附在回复后供用户查看下载。

全文存文件系统（data/conversation_artifacts/），DB 只存元数据；路径统一由
resolve_path 解析，行内只保存相对路径。
"""
import hashlib
import re
import uuid
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from cortexa.db.engine import async_session_factory
from cortexa.db.models import ConversationArtifact

ROOT = Path(__file__).resolve().parents[3] / "data" / "conversation_artifacts"
MAX_PER_TURN = 3
MAX_BYTES = 2 * 1024 * 1024
UNSAFE_NAME = re.compile(r"[\\/:*?\"<>|\r\n\t]+")


def resolve_path(row) -> Path:
    return ROOT / row.path


def blob_path(artifact_id: uuid.UUID) -> Path:
    return ROOT / artifact_id.hex[:2] / f"{artifact_id.hex}.md"


def safe_filename(name: str) -> str:
    cleaned = UNSAFE_NAME.sub("_", (name or "").strip()).strip(". ")
    return (cleaned or "文档.md")[:255]


def detect_format(filename: str) -> str:
    return "markdown" if filename.lower().endswith((".md", ".markdown")) else "text"


async def create_artifact(
    *,
    workspace_id,
    conversation_id,
    owner_user_id,
    agent_id=None,
    title,
    filename,
    content: str,
) -> ConversationArtifact:
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("文档超过 2MB 上限")
    ident = uuid.uuid4()
    path = blob_path(ident)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    artifact = ConversationArtifact(
        id=ident,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        owner_user_id=owner_user_id,
        agent_id=agent_id,
        title=title[:200],
        filename=safe_filename(filename),
        format=detect_format(filename),
        byte_size=len(data),
        content_sha256=hashlib.sha256(data).hexdigest(),
        path=str(path.relative_to(ROOT)),
    )
    async with async_session_factory() as db:
        db.add(artifact)
        await db.commit()
        await db.refresh(artifact)
    return artifact


async def bind_to_message(ids: list[uuid.UUID], message_id: uuid.UUID) -> None:
    if not ids:
        return
    async with async_session_factory() as db:
        await db.execute(
            update(ConversationArtifact)
            .where(ConversationArtifact.id.in_(ids), ConversationArtifact.message_id.is_(None))
            .values(message_id=message_id)
        )
        await db.commit()


async def summaries(ids: list[uuid.UUID]) -> list[dict]:
    if not ids:
        return []
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(ConversationArtifact)
                .where(ConversationArtifact.id.in_(ids))
                .order_by(ConversationArtifact.created_at)
            )
        ).scalars()
        return [
            {
                "id": str(row.id),
                "title": row.title,
                "filename": row.filename,
                "format": row.format,
                "size": row.byte_size,
            }
            for row in rows
        ]


def overwrite(artifact_id: uuid.UUID, content: str) -> tuple[int, str]:
    """Synchronously rewrite the artifact body; returns (byte_size, sha256)."""
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("文档超过 2MB 上限")
    path = blob_path(artifact_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data), hashlib.sha256(data).hexdigest()


class SaveDocumentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200, description="文档标题")
    filename: str = Field(min_length=1, max_length=255, description="文件名，需带 .md 或 .txt 扩展名")
    content: str = Field(min_length=1, max_length=200000, description="文档完整内容（Markdown 或纯文本），必须成文而非提纲")


def save_document_tool(conversation_id, workspace_id, owner_user_id, agent_id=None, created: list | None = None):
    """Per-turn save_document tool; created collects artifact ids for message binding."""
    created = created if created is not None else []

    async def save(title: str, filename: str, content: str) -> dict:
        if len(created) >= MAX_PER_TURN:
            return {"success": False, "error": f"本轮产出物已达上限（{MAX_PER_TURN} 个），请合并内容后再保存"}
        try:
            artifact = await create_artifact(
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                title=title,
                filename=filename,
                content=content,
            )
        except ValueError as error:
            return {"success": False, "error": str(error)}
        created.append(artifact.id)
        return {
            "success": True,
            "artifact_id": str(artifact.id),
            "title": artifact.title,
            "filename": artifact.filename,
            "size": artifact.byte_size,
            "notice": "文档已保存为产出物，将附在本条回复后，用户可查看和下载；请勿在正文中重复粘贴全文。",
        }

    return [
        StructuredTool.from_function(
            coroutine=save,
            name="save_document",
            description=(
                "当用户要求生成文档、方案、报告、清单、纪要等可交付文件时，调用本工具把完整内容保存为产出物；"
                "文档会作为附件附在回复后供用户查看和下载。普通解释性回答不要调用；内容必须完整成文，"
                "不要只写提纲或占位。每轮最多保存 3 个文档。"
            ),
            args_schema=SaveDocumentInput,
        )
    ]
