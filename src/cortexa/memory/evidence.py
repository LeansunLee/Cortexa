"""Evidence is private source material, independently authorized on every read."""

import uuid
from dataclasses import dataclass, field
from sqlalchemy import select
from cortexa.db.models import Conversation, ConversationMessage, AgentCollaboration, DataQuery, Document, Memory
from cortexa.work.models import Work, WorkActivity, WorkDeliverable
from cortexa.security.access import actor_required
from .models import MemoryEvidence
from .policy import digest


@dataclass
class Source:
    type: str
    id: str | None = None
    sub_type: str | None = None
    sub_id: str | None = None
    revision: str | None = None
    mode: str = "explicit"
    summary: str | None = None
    user_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    roots: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def key(self):
        return digest([self.type, self.id, self.sub_type, self.sub_id, self.revision])


def ident(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def source_record(db, source):
    models = {
        "conversation": Conversation,
        "message": ConversationMessage,
        "collaboration": AgentCollaboration,
        "work": Work,
        "work_deliverable": WorkDeliverable,
        "work_activity": WorkActivity,
        "data_query": DataQuery,
        "knowledge": Document,
        "other_agent_memory": Memory,
    }
    model = models.get(source.type)
    if model is None or ident(source.id) is None:
        return None
    # No unscoped reads: Conversation/Work/Data still enforce the source's own ACL.
    obj = await db.scalar(select(model).where(model.id == ident(source.id)))
    if obj is not None and source.type == "conversation" and source.sub_id:
        msg = await db.scalar(
            select(ConversationMessage).where(
                ConversationMessage.id == ident(source.sub_id), ConversationMessage.conversation_id == obj.id
            )
        )
        return msg
    if obj is not None and source.type == "work" and source.sub_id:
        child = WorkDeliverable if source.sub_type == "deliverable" else WorkActivity
        return await db.scalar(select(child).where(child.id == ident(source.sub_id), child.work_id == obj.id))
    if obj is not None and source.type == "knowledge":
        actor = actor_required()
        if not (
            actor.has("knowledge.use")
            or actor.has("knowledge.manage")
            or actor.operations_knowledge_id == obj.knowledge_base_id
        ):
            return None
    return obj


async def validate_source(db, source):
    if source.type in {"manual", "human_feedback"}:
        return source.user_id == actor_required().user_id
    record = await source_record(db, source)
    if record is None:
        return False
    if source.revision and isinstance(record, (ConversationMessage, AgentCollaboration)):
        await db.refresh(record)
        content = record.content if isinstance(record, ConversationMessage) else record.result_content
        return digest(content) == source.revision
    return True


async def append_evidence(db, mem, source, stance="supports"):
    existing = await db.scalar(
        select(MemoryEvidence).where(MemoryEvidence.memory_id == mem.id, MemoryEvidence.evidence_key == source.key)
    )
    if existing:
        return existing, False
    evidence = MemoryEvidence(
        workspace_id=mem.workspace_id,
        agent_id=mem.agent_id,
        memory_id=mem.id,
        source_type=source.type,
        source_id=str(source.id) if source.id else None,
        source_sub_type=source.sub_type,
        source_sub_id=source.sub_id,
        source_revision=source.revision,
        source_mode=source.mode,
        stance=stance,
        source_user_id=source.user_id,
        source_agent_id=source.agent_id,
        summary=(source.summary or "")[:1000] or None,
        source_status="available",
        evidence_key=source.key,
        root_keys=sorted(set(source.roots or [source.key])),
        metadata_json=source.metadata,
    )
    db.add(evidence)
    await db.flush()
    return evidence, True


async def visible_evidence(db, row):
    source = Source(row.source_type, row.source_id, row.source_sub_type, row.source_sub_id, user_id=row.source_user_id)
    allowed = row.source_status == "available" and await validate_source(db, source)
    result = {
        "id": str(row.id),
        "source_type": row.source_type if row.source_type not in {"conversation", "message"} else "conversation",
        "source_status": row.source_status,
        "accessible": bool(allowed),
        "stance": row.stance,
        "label": "内部业务沟通" if row.source_type in {"conversation", "message", "collaboration"} else "业务依据",
    }
    if allowed:
        result.update(
            source_id=row.source_id,
            source_sub_id=row.source_sub_id,
            summary=row.summary,
            source_user_id=str(row.source_user_id) if row.source_user_id else None,
            source_agent_id=str(row.source_agent_id) if row.source_agent_id else None,
            source_mode=row.source_mode,
            recorded_at=row.created_at.isoformat(),
        )
    return result
