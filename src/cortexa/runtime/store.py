"""Short transactions for Goal ownership, idempotency and revision CAS checkpoints."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from cortexa.api.conversation_titles import assign_first_message_title
from cortexa.db.engine import async_session_factory
from cortexa.db.models import Conversation, ConversationMessage
from cortexa.runtime.artifacts import ArtifactStore
from cortexa.runtime.models import RuntimeGoal
from cortexa.runtime.state import GoalStatus
from cortexa.security.access import actor_required, require_agent_use


def owned(goal_id=None):
    actor = actor_required()
    conditions = [RuntimeGoal.workspace_id == actor.workspace_id, RuntimeGoal.owner_user_id == actor.user_id]
    if goal_id is not None:
        conditions.append(RuntimeGoal.id == goal_id)
    return conditions


async def own_conversation(db, conv_id, *, use_agent=False):
    actor = actor_required()
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.owner_user_id != actor.user_id or conv.workspace_id != actor.workspace_id:
        raise HTTPException(404, "对话不存在或无权访问")
    if use_agent:
        await require_agent_use(db, conv.agent_id)
    return conv


class GoalStore:
    def __init__(self, sessions=async_session_factory, files=None):
        self.sessions = sessions
        self.files = files or ArtifactStore()

    async def get(self, conv_id, goal_id):
        async with self.sessions() as db:
            await own_conversation(db, conv_id)
            row = (
                await db.execute(select(RuntimeGoal).where(*owned(goal_id), RuntimeGoal.conversation_id == conv_id))
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(404, "Goal 不存在或无权访问")
            return row

    async def create(self, conv_id, key, content, state, payload):
        actor = actor_required()
        request_content = (
            json.dumps(
                [content, payload.get("participant_tasks", {}), payload.get("participant_inputs", {})],
                sort_keys=True,
                ensure_ascii=False,
            )
            if payload.get("participant_tasks") or payload.get("participant_inputs")
            else content
        )
        digest = hashlib.sha256(request_content.encode()).hexdigest()
        async with self.sessions() as db:
            # Serialize creation within one conversation. The unique constraint also
            # rejects same Workspace/user keys racing across different conversations.
            await db.execute(select(Conversation.id).where(Conversation.id == conv_id).with_for_update())
            conv = await own_conversation(db, conv_id, use_agent=True)
            existing = (
                await db.execute(select(RuntimeGoal).where(*owned(), RuntimeGoal.idempotency_key == key))
            ).scalar_one_or_none()
            if existing:
                if existing.conversation_id != conv_id or existing.state.get("request_hash") != digest:
                    raise HTTPException(409, "幂等键已用于不同请求")
                return existing, False
            payload["conversation_title"] = await assign_first_message_title(db, conv_id, content)
            goal_id, message_id = uuid.uuid4(), uuid.uuid4()
            state.request_hash = digest
            state.latest_message_id = str(message_id)
            ref = self.files.write(goal_id, payload)
            db.add(
                ConversationMessage(
                    id=message_id,
                    conversation_id=conv_id,
                    role="user",
                    content=content,
                    metadata_json={"goal_id": str(goal_id), "runtime_version": state.version},
                )
            )
            await db.flush()
            # Message was created in this exact conversation in this transaction.
            row = RuntimeGoal(
                id=goal_id,
                workspace_id=conv.workspace_id,
                owner_user_id=actor.user_id,
                conversation_id=conv_id,
                initial_message_id=message_id,
                agent_id=conv.agent_id,
                idempotency_key=key,
                status=state.status,
                revision=1,
                state=state.model_dump(mode="json"),
                artifacts={"snapshot": ref},
            )
            db.add(row)
            try:
                await db.commit()
            except IntegrityError as error:
                await db.rollback()
                raise HTTPException(409, "幂等键冲突，请读取原 Goal") from error
            return row, True

    async def checkpoint(self, row, state, payload, *, reply=None, trace=None, stats=None, resume_content=None):
        encoded = state.model_dump(mode="json")
        if len(json.dumps(encoded).encode()) > 65536:
            raise ValueError("goal_state_size_limit")
        ref = self.files.write(row.id, payload)
        actor = actor_required()
        async with self.sessions() as db:
            conv = await own_conversation(db, row.conversation_id)
            if conv.agent_id != row.agent_id:
                raise HTTPException(409, "对话 Agent 已改变，不能继续旧 Goal")
            if resume_content is not None:
                user_id = uuid.uuid4()
                db.add(
                    ConversationMessage(
                        id=user_id,
                        conversation_id=conv.id,
                        role="user",
                        content=resume_content,
                        metadata_json={"goal_id": str(row.id), "runtime_version": state.version},
                    )
                )
                state.latest_message_id = str(user_id)
            message = None
            if reply is not None:
                message = ConversationMessage(
                    id=uuid.uuid4(),
                    conversation_id=conv.id,
                    role="assistant",
                    content=reply,
                    metadata_json={
                        "goal_id": str(row.id),
                        "runtime_version": state.version,
                        "goal_status": state.status,
                        "stopped": state.reason == "cancelled",
                        "sources": payload.get("sources", []),
                        "collaborations": [
                            {
                                **{k: v for k, v in c.items() if k != "result"},
                                "goal_result": {
                                    "conversation_id": str(conv.id),
                                    "goal_id": str(row.id),
                                    "action_id": c["action_id"],
                                },
                            }
                            for c in payload.get("collaborations", [])
                            if c.get("action_id")
                        ],
                        "debug_trace": trace or [],
                        "stats": stats or {},
                    },
                )
                db.add(message)
                state.result_message_id = str(message.id)
            values = dict(
                status=state.status,
                revision=row.revision + 1,
                state=state.model_dump(mode="json"),
                artifacts={"snapshot": ref},
                updated_at=datetime.now(UTC),
                completed_at=datetime.now(UTC) if state.status in {GoalStatus.COMPLETE, GoalStatus.FAILED} else None,
            )
            result = await db.execute(
                update(RuntimeGoal)
                .where(
                    RuntimeGoal.id == row.id,
                    RuntimeGoal.workspace_id == actor.workspace_id,
                    RuntimeGoal.owner_user_id == actor.user_id,
                    RuntimeGoal.conversation_id == conv.id,
                    RuntimeGoal.revision == row.revision,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                await db.rollback()
                raise HTTPException(409, "Goal 已更新，请重新读取状态")
            await db.commit()
        # Detached row is only a version token; never blindly merge it into a session.
        for key, value in values.items():
            setattr(row, key, value)
        return message
