"""Cookie authentication, CSRF origin checks and fail-closed API authorization."""

import asyncio
import uuid
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from agentdevstu.db.engine import async_session_factory
from agentdevstu.db.models import Conversation, Agent
from agentdevstu.db.meetings import Meeting, MeetingParticipant
from sqlalchemy import select
from .access import current_actor, actor_required, load_actor, require, require_agent_use, raw
from .models import ProtectedUpload
from . import isolation  # noqa: F401

COOKIE = "agentdevstu_session"


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = request.url.path
        protected = (
            path.startswith("/api/") or path.startswith("/uploads/") or path in ("/docs", "/redoc", "/openapi.json")
        )
        if not protected:
            return await self.app(scope, receive, send)
        try:
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if request.headers.get("x-requested-with") != "AgentDevStu":
                    raise HTTPException(403, "缺少请求校验标识")
                if origin and urlsplit(origin).netloc != request.headers.get("host"):
                    raise HTTPException(403, "不允许跨站请求")
                if request.headers.get("sec-fetch-site") == "cross-site":
                    raise HTTPException(403, "不允许跨站请求")
            if path == "/api/auth/login" and request.method == "POST":
                return await self.app(scope, receive, send)
            token = request.cookies.get(COOKIE, "")
            actor = await load_actor(token) if token else None
            if actor is None:
                raise HTTPException(401, "登录已过期，请重新登录")
            if path in ("/docs", "/redoc", "/openapi.json") and not actor.has("config.manage"):
                raise HTTPException(403, "没有此操作权限")
            if actor.must_change and path not in ("/api/auth/me", "/api/auth/password", "/api/auth/logout"):
                raise HTTPException(403, "首次登录请先修改密码")
            ws = request.headers.get("x-workspace-id") or request.query_params.get("workspace_id")
            if ws:
                try:
                    actor.workspace_id = uuid.UUID(ws)
                except ValueError:
                    raise HTTPException(422, "工作空间 ID 格式不正确")
            if path.startswith("/uploads/"):
                async with async_session_factory() as db:
                    upload = await db.get(ProtectedUpload, path)
                    if upload:
                        if upload.user_id != actor.user_id or upload.workspace_id not in actor.memberships:
                            raise HTTPException(404, "文件不存在或无权访问")
                        actor.workspace_id = upload.workspace_id
                    elif not path.startswith("/uploads/avatars/"):
                        raise HTTPException(404, "历史附件尚未分配所有者")
            from agentdevstu.memory.integration import request_session_token
            session_ctx = request_session_token.set(token)
            ctx_token = current_actor.set(actor)
            initial = actor.signature()
            started = False
            streaming = False
            revoked = False
            monitor = None

            async def still_authorized():
                fresh = await load_actor(token)
                if fresh is None or fresh.signature() != initial:
                    return False
                fresh.workspace_id = actor.workspace_id
                if actor.runtime_agent_ids:
                    async with async_session_factory() as db:
                        agents = (
                            (await db.execute(raw(select(Agent).where(Agent.id.in_(actor.runtime_agent_ids)))))
                            .scalars()
                            .all()
                        )
                    if len(agents) != len(actor.runtime_agent_ids) or any(not fresh.can_use(a) for a in agents):
                        return False
                return True

            async def watch_authorization():
                nonlocal revoked
                try:
                    while True:
                        await asyncio.sleep(2)
                        if not await still_authorized():
                            revoked = True
                            application_task.cancel()
                            return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # An unavailable authorization database must not leave a stream running unchecked.
                    revoked = True
                    application_task.cancel()

            async def checked_send(message):
                nonlocal started, streaming, monitor
                if message["type"] == "http.response.start":
                    started = True
                    headers = list(message.get("headers", []))
                    streaming = any(k == b"content-type" and b"text/event-stream" in v for k, v in headers)
                    headers += [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
                    if path.startswith("/uploads/"):
                        headers.append((b"content-security-policy", b"sandbox; default-src 'none'"))
                        if not path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                            headers.append((b"content-disposition", b"attachment"))
                    message["headers"] = headers
                    if streaming:
                        monitor = asyncio.create_task(watch_authorization())
                await send(message)

            application_task = asyncio.create_task(self.app(scope, receive, checked_send))
            try:
                await application_task
            except asyncio.CancelledError:
                if not revoked:
                    raise
                if started:
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b'data: {"type":"error","error":"Authorization changed; reconnect required"}\n\n',
                            "more_body": False,
                        }
                    )
            finally:
                if monitor:
                    monitor.cancel()
                    try:
                        await monitor
                    except asyncio.CancelledError:
                        pass
                current_actor.reset(ctx_token)
                request_session_token.reset(session_ctx)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)


async def authorize_request(request: Request):
    path = request.url.path
    if not path.startswith("/api/"):
        if path in ("/docs", "/redoc", "/openapi.json"):
            require("config.manage")
        return
    if path.startswith("/api/auth/") or path.startswith("/api/admin/"):
        return  # Authentication middleware + explicit security-service checks.
    actor = actor_required()
    parts = path.removeprefix("/api/").strip("/").split("/")
    module = parts[0]
    method = request.method
    if module == "config":
        require("config.manage")
        return
    if module == "chat":
        # Legacy process-global chat sessions have no owner; retire this bypass entirely.
        raise HTTPException(410, "请使用已授权 Agent 的对话接口")
    if module == "workspaces":
        if method == "POST":
            require("workspaces.create")
        elif method != "GET":
            if len(parts) < 2:
                raise HTTPException(404)
            try:
                actor.workspace_id = uuid.UUID(parts[1])
            except ValueError:
                raise HTTPException(422)
            require("workspace.manage")
        return
    if actor.workspace_id not in actor.memberships:
        raise HTTPException(403, "请先加入并选择工作空间")
    if module == "organization":
        if method != "GET":
            require("members.manage")
        return
    if module in ("works", "work-candidates"):
        return  # Workspace membership above; Work service validates participants and actions.
    if module == "agents":
        if method == "GET":
            require("agent.read")
        elif parts[-1] == "publish":
            require("agent.publish")
        elif method == "DELETE":
            require("agent.delete")
        elif len(parts) == 1 and method == "POST":
            require("agent.create")
        else:
            require("agent.update")
    elif module == "agent-operations":
        require("agent.operate")
        require("agent.use")
        actor.runtime = True
        if len(parts) < 2:
            raise HTTPException(404)
        try:
            operation_agent_id = uuid.UUID(parts[1])
        except ValueError:
            raise HTTPException(422)
        async with async_session_factory() as db:
            await require_agent_use(db, operation_agent_id)
    elif module in ("conversations", "collaboration"):
        require("agent.use")
        actor.runtime = True
        async with async_session_factory() as db:
            conv_id = None
            if module == "conversations" and len(parts) > 1:
                conv_id = parts[1]
            if module == "collaboration" and len(parts) > 2:
                conv_id = parts[2]
            if conv_id:
                try:
                    conv = await db.get(Conversation, uuid.UUID(conv_id))
                except ValueError:
                    raise HTTPException(422)
                if conv is None:
                    raise HTTPException(404, "对话不存在或无权访问")
                if method != "GET" and method != "DELETE" and conv.agent_id:
                    await require_agent_use(db, conv.agent_id)
            elif module == "conversations" and method == "POST":
                body = await request.json()
                try:
                    agent_id = uuid.UUID(body.get("agent_id", ""))
                except (ValueError, TypeError, AttributeError):
                    raise HTTPException(422, "请选择已获授权的 Agent")
                await require_agent_use(db, agent_id)
            if method == "POST" and request.headers.get("content-type", "").startswith("application/json"):
                body = await request.json()
                await validate_attachments(db, body.get("attachments") or [], conv_id)
    elif module == "meetings":
        require("meeting.use")
        require("agent.use")
        actor.runtime = True
        async with async_session_factory() as db:
            if len(parts) > 1 and parts[1] != "upload":
                try:
                    meeting = await db.get(Meeting, uuid.UUID(parts[1]))
                except ValueError:
                    raise HTTPException(422)
                if meeting is None:
                    raise HTTPException(404, "会议不存在或无权访问")
                if parts[-1] in ("start", "stream"):
                    ids = (
                        await db.execute(
                            select(MeetingParticipant.agent_id).where(MeetingParticipant.meeting_id == meeting.id)
                        )
                    ).scalars()
                    for ident in ids:
                        if ident:
                            await require_agent_use(db, ident)
            elif len(parts) == 1 and method == "POST":
                body = await request.json()
                ids = body.get("participant_agent_ids") or []
                if body.get("host_agent_id"):
                    ids = [*ids, body["host_agent_id"]]
                if not ids:
                    raise HTTPException(422, "请至少选择一个 Agent")
                for ident in ids:
                    try:
                        await require_agent_use(db, uuid.UUID(ident))
                    except ValueError:
                        raise HTTPException(422)
                await validate_attachments(db, body.get("attachments") or [])
    else:
        code = {
            "data": "data.manage",
            "tools": "tools.manage",
            "workflows": "workflows.manage",
            "tasks": "tasks.manage",
            "memories": "agent.operate",
        }.get(module)
        if module == "knowledge":
            # Grant maintenance only to this Agent's private knowledge base.
            if len(parts) > 1 and actor.has("agent.operate") and actor.has("agent.use"):
                from agentdevstu.db.models import KnowledgeBase
                try:
                    kb_id = uuid.UUID(parts[1])
                except ValueError:
                    kb_id = None
                if kb_id:
                    async with async_session_factory() as db:
                        kb = await db.get(KnowledgeBase, kb_id)
                        if kb and kb.agent_id:
                            await require_agent_use(db, kb.agent_id)
                            actor.operations_knowledge_id = kb.id
                            return
            # Knowledge routes enforce read/manage/ownership rules in the API.
            if method == "GET":
                if not (actor.has("knowledge.manage") or actor.has("knowledge.use")):
                    raise HTTPException(403, "没有使用知识库权限")
            elif not (actor.has("knowledge.manage") or actor.has("knowledge.use")):
                raise HTTPException(403, "没有使用知识库权限")
            return
        if code is None:
            raise HTTPException(404, "接口不存在")
        require(code)


async def validate_attachments(db, attachments, conv_id=None):
    actor = actor_required()
    for item in attachments:
        path = item.get("url") or item.get("path")
        upload = await db.get(ProtectedUpload, path) if path else None
        if (
            upload is None
            or upload.user_id != actor.user_id
            or upload.workspace_id != actor.workspace_id
            or (conv_id and str(upload.conversation_id) != str(conv_id))
        ):
            raise HTTPException(403, "附件不属于当前用户和对话")
