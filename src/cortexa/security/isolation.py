"""ORM defense in depth: scope lists, ID lookups, joins and independent runtime sessions."""

import uuid
from fastapi import HTTPException
from sqlalchemy import event, select, inspect, and_
from sqlalchemy.orm import Session, with_loader_criteria
from cortexa.db.engine import Base
from cortexa.db import models as m
from cortexa.db import meetings as mm
from .access import current_actor
from cortexa.runtime.models import RuntimeGoal

PRIVATE = (m.Conversation, mm.Meeting, m.Task, m.AgentRun, m.TaskRun, m.DataQuery, RuntimeGoal)


def criteria(actor):
    ws = actor.workspace_id
    membership_ids = list(actor.memberships)
    rules = {m.Workspace: m.Workspace.id.in_(membership_ids)}
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if model.__module__.startswith("cortexa.security"):
            continue
        if hasattr(model, "workspace_id"):
            rules[model] = model.workspace_id == ws if ws else model.workspace_id.in_([])
    for model in PRIVATE:
        # Even administrators do not silently read another person's conversations/memories.
        own = model.owner_user_id == actor.user_id
        rules[model] = and_(rules.get(model, True), own)
    if ws:
        member = actor.memberships.get(ws, {})
        if actor.runtime or not actor.has("agent.read"):
            allowed = (
                True
                if actor.superadmin or member.get("all_agents")
                else m.Agent.id.in_(list(member.get("agent_ids", [])))
            )
            rules[m.Agent] = and_(m.Agent.workspace_id == ws, m.Agent.status == "active", allowed)
    from cortexa.memory.models import MemoryEvidence, MemoryEvent, MemoryIssue, MemoryRelation
    member = actor.memberships.get(ws, {})
    agent_allowed = True if actor.superadmin or member.get("all_agents") else m.Agent.id.in_(list(member.get("agent_ids", [])))
    memory_agents = select(m.Agent.__table__.c.id).where(
        m.Agent.__table__.c.workspace_id == ws, m.Agent.__table__.c.status == "active",
        agent_allowed, actor.has("agent.use"),
    )
    rules[m.Memory] = and_(m.Memory.workspace_id == ws, m.Memory.agent_id.in_(memory_agents))
    for child in (MemoryEvidence, MemoryEvent, MemoryIssue):
        rules[child] = and_(child.workspace_id == ws, child.agent_id.in_(memory_agents))
    visible_memories = select(m.Memory.__table__.c.id).where(rules[m.Memory])
    rules[MemoryRelation] = and_(MemoryRelation.workspace_id == ws,
        MemoryRelation.from_memory_id.in_(visible_memories), MemoryRelation.to_memory_id.in_(visible_memories))
    from cortexa.work.models import Work, WorkCandidate, WorkDeliverable, WorkActivity
    from cortexa.work.service import visibility
    rules[Work] = visibility(actor)
    rules[WorkCandidate] = and_(WorkCandidate.workspace_id == ws, WorkCandidate.owner_user_id == actor.user_id)
    # Each child inherits its parent's restrictions; use Core tables to avoid recursive criteria.
    children = [
        (WorkDeliverable, "work_id", Work),
        (WorkActivity, "work_id", Work),
        (m.AgentVersion, "agent_id", m.Agent),
        (m.AgentRun, "agent_id", m.Agent),
        (m.Document, "knowledge_base_id", m.KnowledgeBase),
        (m.DocumentChunk, "knowledge_base_id", m.KnowledgeBase),
        (m.ConversationMessage, "conversation_id", m.Conversation),
        (m.AgentCollaboration, "conversation_id", m.Conversation),
        (m.WorkflowNode, "workflow_id", m.Workflow),
        (m.WorkflowEdge, "workflow_id", m.Workflow),
        (m.TaskRun, "task_id", m.Task),
        (m.DataSchema, "data_source_id", m.DataSource),
        (m.AgentDataBinding, "agent_id", m.Agent),
        (mm.MeetingParticipant, "meeting_id", mm.Meeting),
        (mm.MeetingRound, "meeting_id", mm.Meeting),
        (mm.MeetingMessage, "meeting_id", mm.Meeting),
        (mm.MeetingConclusion, "meeting_id", mm.Meeting),
        (mm.TodoItem, "meeting_id", mm.Meeting),
    ]
    for child, key, parent in children:
        condition = getattr(child, key).in_(select(parent.__table__.c.id).where(rules[parent]))
        rules[child] = and_(rules.get(child, True), condition)
    return rules


@event.listens_for(Session, "do_orm_execute")
def scope_reads(state):
    actor = current_actor.get()
    if state.execution_options.get("security_unscoped") or not state.is_select:
        return
    if actor is None:
        from cortexa.memory.models import MemoryEvidence, MemoryEvent, MemoryIssue, MemoryRelation
        for model in (m.Memory, MemoryEvidence, MemoryEvent, MemoryIssue, MemoryRelation):
            state.statement = state.statement.options(with_loader_criteria(model, False, include_aliases=True))
        return
    for model, condition in criteria(actor).items():
        state.statement = state.statement.options(with_loader_criteria(model, condition, include_aliases=True))


@event.listens_for(Session, "before_flush")
def scope_writes(session, flush_context, instances):
    actor = current_actor.get()
    if actor is None:
        return
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if obj.__class__.__module__.startswith("cortexa.security"):
            continue
        is_new = obj in session.new
        if isinstance(obj, m.Workspace):
            continue  # Workspace creation is system-authorized and auto-enrolls its creator.
        if hasattr(obj, "workspace_id") and obj.workspace_id != actor.workspace_id:
            raise HTTPException(403, "资源不属于当前工作空间")
        if hasattr(obj, "owner_user_id") and not isinstance(obj, m.Memory):
            if is_new:
                obj.owner_user_id = actor.user_id
            elif obj.owner_user_id != actor.user_id:
                raise HTTPException(403, "不能操作其他用户的数据")
        mapper = inspect(obj).mapper
        for column in mapper.columns:
            for fk in column.foreign_keys:
                # Nullable composite foreign keys do not reference a row when any component is null.
                if len(fk.constraint.elements) > 1 and any(
                    getattr(obj, element.parent.key) is None for element in fk.constraint.elements
                ):
                    continue
                target_model = next(
                    (x.class_ for x in Base.registry.mappers if x.local_table.name == fk.column.table.name), None
                )
                if target_model is None or target_model.__module__.startswith("cortexa.security"):
                    continue
                # A user's history remains deletable after its Agent is unpublished
                # or its grant is revoked. Ownership/workspace checks above still
                # apply; creating/updating a conversation still validates its Agent.
                if obj in session.deleted and isinstance(obj, m.Conversation) and target_model is m.Agent:
                    continue
                value = getattr(obj, column.key)
                if value is None:
                    continue
                if isinstance(value, str):
                    try:
                        value = uuid.UUID(value)
                    except ValueError:
                        raise HTTPException(422, "资源 ID 格式不正确")
                # Parent newly flushed in the same transaction is already owner/workspace checked.
                target = session.scalar(select(target_model).where(getattr(target_model, fk.column.key) == value))
                if target is None:
                    raise HTTPException(403, "关联资源不存在或无权访问")
        if isinstance(obj, m.Agent):
            for attr, model in [("knowledge_base_ids", m.KnowledgeBase), ("tool_ids", m.Tool)]:
                for ident in getattr(obj, attr) or []:
                    if session.scalar(select(model).where(model.id == uuid.UUID(str(ident)))) is None:
                        raise HTTPException(403, "不能绑定其他工作空间的资源")
