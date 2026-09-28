"""Context propagates through asyncio child tasks and asyncio.to_thread."""

import inspect
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps

current_usage = ContextVar("model_usage_context", default=None)
SOURCES = {
    "config": "configuration",
    "conversations": "conversation",
    "collaboration": "conversation",
    "meetings": "meeting",
    "agents": "system",
    "agent-operations": "agent_operations",
    "knowledge": "knowledge",
    "works": "work",
    "work-candidates": "work",
    "workflows": "workflow",
    "tasks": "workflow",
    "data": "data_assistant",
    "memories": "memory",
}


def root_context(source="system", object_type=None, object_id=None, trigger="system"):
    return {
        "operation_id": str(uuid.uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "source": source,
        "trigger": trigger,
        "object_type": object_type,
        "object_id": object_id,
        "step_id": str(uuid.uuid4()),
        "action": "model_call",
    }


class UsageMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        parts = scope.get("path", "").strip("/").split("/")
        source = SOURCES.get(parts[1], "system") if len(parts) > 1 else "system"
        ident = None
        if len(parts) > 2:
            try:
                ident = str(uuid.UUID(parts[2]))
            except ValueError:
                pass
        token = current_usage.set(root_context(source, source, ident, "user"))
        try:
            await self.app(scope, receive, send)
        finally:
            current_usage.reset(token)


def annotate_usage(*, agent=None, action=None, **values):
    """Annotate the current task before creating a model; never mutate shared dicts."""
    ctx = dict(current_usage.get() or root_context())
    if agent is not None:
        ctx.update(
            agent_id=str(agent.id),
            agent_name=agent.name,
            workspace_id=str(agent.workspace_id) if getattr(agent, "workspace_id", None) else None,
        )
    if action:
        ctx["action"] = action
    ctx.update({key: str(value) for key, value in values.items() if value is not None})
    current_usage.set(ctx)


@contextmanager
def usage_scope(action, *, source=None, background=False, **values):
    previous = current_usage.get()
    ctx = dict(previous or root_context(source or "system"))
    ctx.update(parent_step_id=ctx.get("step_id"), step_id=str(uuid.uuid4()), action=action)
    if source and not previous:
        ctx["source"] = source
    if background:
        ctx["trigger"] = "background"
    ctx.update({k: str(v) for k, v in values.items() if v is not None})
    token = current_usage.set(ctx)
    try:
        yield
    finally:
        current_usage.reset(token)


def usage_action(action, *, source=None, background=False):
    def decorate(fn):
        signature = inspect.signature(fn, eval_str=True)

        def scope(args, kwargs):
            bound = signature.bind_partial(*args, **kwargs).arguments
            values = {}
            for key in ("conv_id", "conversation_id", "meeting_id", "doc_id", "document_id", "work_id", "workflow_id"):
                if bound.get(key) is not None:
                    values.update(object_id=bound[key], object_type=key.removesuffix("_id"))
                    break
            for name in ("agent", "target_agent"):
                agent = bound.get(name)
                if agent is not None:
                    values.update(
                        agent_id=getattr(agent, "id", None),
                        agent_name=getattr(agent, "name", None),
                        workspace_id=getattr(agent, "workspace_id", None),
                    )
            return usage_scope(action, source=source, background=background, **values)

        if inspect.isasyncgenfunction(fn):

            @wraps(fn)
            async def wrapper(*args, **kwargs):
                with scope(args, kwargs):
                    async for item in fn(*args, **kwargs):
                        yield item
        elif inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def wrapper(*args, **kwargs):
                with scope(args, kwargs):
                    return await fn(*args, **kwargs)
        else:

            @wraps(fn)
            def wrapper(*args, **kwargs):
                with scope(args, kwargs):
                    return fn(*args, **kwargs)

        wrapper.__signature__ = signature
        return wrapper

    return decorate
