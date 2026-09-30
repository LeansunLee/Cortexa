from __future__ import annotations

import json
import sys
import re
import traceback
import uuid
import asyncio
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse as _BaseFileResponse
from starlette.staticfiles import StaticFiles as _BaseStaticFiles
from starlette.responses import Response


class CacheControlStaticFiles(_BaseStaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if isinstance(response, _BaseFileResponse):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from cortexa.config.settings import load_env
from cortexa.workflow.graph import build_graph
from cortexa.api.router import api_router
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[3]
from cortexa.security.http import SecurityMiddleware, authorize_request
app = FastAPI(title="Cortexa", version="0.1.0", dependencies=[Depends(authorize_request)])


@app.exception_handler(RequestValidationError)
async def localized_memory_validation(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/memories") or ("/memories" in request.url.path and request.url.path.startswith("/api/agent-operations/")):
        for error in exc.errors():
            empty_content = error.get("type") == "missing" or error.get("input") is None or isinstance(error.get("input"), str) and not error["input"].strip()
            if "content" in error.get("loc", ()) and empty_content:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "记忆内容不能为空"}, status_code=422)
    return await request_validation_exception_handler(request, exc)

from cortexa.usage.context import UsageMiddleware
app.add_middleware(UsageMiddleware)
app.add_middleware(SecurityMiddleware)

app.include_router(api_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> HTMLResponse:
    import traceback
    tb = traceback.format_exc()
    print(f"[ERROR] {request.method} {request.url} -> {exc}", file=sys.stderr)
    print(tb, file=sys.stderr)
    return HTMLResponse(
        content=f"<pre>Internal Server Error\n{exc}</pre>",
        status_code=500,
    )
app.mount("/static", CacheControlStaticFiles(directory=Path(__file__).parent / "static"), name="static")

# Serve uploaded files (avatars etc.)
UPLOADS_DIR = Path(__file__).resolve().parents[3] / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

load_env()


@app.on_event("startup")
async def start_usage_collector():
    from cortexa.usage.collector import start
    await start()


@app.on_event("shutdown")
async def stop_usage_collector():
    from cortexa.usage.collector import stop
    await stop()


@app.on_event("startup")
async def recover_knowledge_jobs() -> None:
    """Resume PDF jobs lost with the previous process."""
    try:
        from cortexa.api import knowledge
        knowledge._recovery_task = asyncio.create_task(knowledge.recover_pdf_jobs())
        def report_failure(task):
            if not task.cancelled() and task.exception():
                print(f"[PDF] Recovery failed: {task.exception()}", file=sys.stderr)
        knowledge._recovery_task.add_done_callback(report_failure)
    except Exception as error:
        # Startup must remain available even when the database is temporarily down.
        print(f"[PDF] Startup recovery failed: {type(error).__name__}: {error}", file=sys.stderr)


@app.on_event("shutdown")
async def stop_knowledge_recovery() -> None:
    from cortexa.api import knowledge
    task = knowledge._recovery_task
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Create tables on startup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------
sessions: dict[str, dict[str, Any]] = {}


def _get_config_path() -> Path:
    return ROOT / "config.yaml"


def _load_config() -> dict[str, Any]:
    p = _get_config_path()
    if not p.exists():
        return {"llm": {"default": "openai", "providers": {}}}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(data: dict[str, Any]) -> None:
    p = _get_config_path()
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _save_env(updates: dict[str, str]) -> None:
    env_path = ROOT / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    keys_written: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            keys_written.add(key)
        else:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in keys_written:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Vue SPA support
DIST_DIR = Path(__file__).parent / "static" / "dist"

@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request) -> HTMLResponse:
    """Serve Vue SPA"""
    from fastapi.responses import FileResponse
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return templates.TemplateResponse(request, "dashboard.html")


# ---------------------------------------------------------------------------
# Config API
# ---------------------------------------------------------------------------
class ProviderPayload(BaseModel):
    name: str
    kind: str = "openai"
    model: str = "gpt-4o-mini"
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096


class DefaultPayload(BaseModel):
    default: str


class ConversationDebugPayload(BaseModel):
    enabled: bool


@app.get("/api/config/providers")
async def list_provider_names() -> dict[str, Any]:
    """Return provider names and models for model selectors."""
    cfg = _load_config()
    providers = cfg.get("llm", {}).get("providers", {})
    result = {}
    for name, prov in providers.items():
        result[name] = {
            "kind": prov.get("kind", "openai"),
            "model": prov.get("model", ""),
        }
    return {"providers": result}


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    cfg = _load_config()
    providers = cfg.get("llm", {}).get("providers", {})
    default = cfg.get("llm", {}).get("default", "openai")

    env_path = ROOT / ".env"
    env_vars: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip()

    result: dict[str, Any] = {
        "default": default,
        "default_provider": default,
        "providers": {},
        "conversation_debug_enabled": bool(
            cfg.get("features", {}).get("conversation_debug_enabled", False)
        ),
    }
    for name, prov in providers.items():
        api_key_env = prov.get("api_key", "")
        resolved_key = ""
        if api_key_env.startswith("${") and api_key_env.endswith("}"):
            var_name = api_key_env[2:-1]
            resolved_key = env_vars.get(var_name, "")
        elif api_key_env:
            resolved_key = api_key_env

        result["providers"][name] = {
            "kind": prov.get("kind", "openai"),
            "model": prov.get("model", ""),
            "base_url": prov.get("base_url", ""),
            "api_key_ref": api_key_env,
            "api_key_set": bool(resolved_key),
            "temperature": prov.get("temperature", 0.2),
            "max_tokens": prov.get("max_tokens", 4096),
        }

    # Add embedding config
    embedding_provider = cfg.get("llm", {}).get("embedding_provider", "")
    embedding_model = cfg.get("llm", {}).get("embedding_model", "text-embedding-3-small")
    result["embedding_provider"] = embedding_provider
    result["embedding_model"] = embedding_model

    return result


@app.post("/api/config/conversation-debug")
async def save_conversation_debug_config(payload: ConversationDebugPayload) -> dict[str, Any]:
    """Enable or disable collection and display of conversation debug traces."""
    cfg = _load_config()
    features = cfg.setdefault("features", {})
    features["conversation_debug_enabled"] = payload.enabled
    _save_config(cfg)
    return {"status": "ok", "enabled": payload.enabled}


class EmbeddingPayload(BaseModel):
    provider: str = ""
    model: str = "text-embedding-3-small"


@app.post("/api/config/embedding")
async def save_embedding_config(payload: EmbeddingPayload) -> dict[str, Any]:
    """Save embedding model configuration."""
    cfg = _load_config()
    llm = cfg.setdefault("llm", {})
    llm["embedding_provider"] = payload.provider
    llm["embedding_model"] = payload.model
    _save_config(cfg)
    return {"status": "ok", "provider": payload.provider, "model": payload.model}


@app.post("/api/config/provider")
async def save_provider(payload: ProviderPayload) -> dict[str, Any]:
    cfg = _load_config()
    llm = cfg.setdefault("llm", {})
    providers = llm.setdefault("providers", {})

    safe_key = re.sub(r"[^A-Za-z0-9]", "", payload.name.upper())
    env_var_name = f"{safe_key}_API_KEY"

    providers[payload.name] = {
        "kind": payload.kind,
        "model": payload.model,
        "base_url": payload.base_url,
        "api_key": f"${{{env_var_name}}}",
        "temperature": payload.temperature,
        "max_tokens": payload.max_tokens,
    }

    _save_config(cfg)

    if payload.api_key:
        _save_env({env_var_name: payload.api_key})

    load_env()


# ---------------------------------------------------------------------------
# Create tables on startup
# ---------------------------------------------------------------------------

@app.post("/api/config/default")
async def set_default_provider(payload: DefaultPayload) -> dict[str, Any]:
    cfg = _load_config()
    llm = cfg.setdefault("llm", {})
    llm["default"] = payload.default
    _save_config(cfg)
    return {"status": "ok", "default": payload.default}


@app.delete("/api/config/provider/{name}")
async def delete_provider(name: str) -> dict[str, Any]:
    cfg = _load_config()
    providers = cfg.get("llm", {}).get("providers", {})
    if name not in providers:
        return {"status": "error", "message": "Provider not found"}
    del providers[name]
    _save_config(cfg)
    return {"status": "ok"}


@app.put("/api/config/provider/{name}")
async def update_provider(name: str, payload: ProviderPayload) -> dict[str, Any]:
    cfg = _load_config()
    llm = cfg.setdefault("llm", {})
    providers = llm.setdefault("providers", {})
    if name not in providers:
        return {"status": "error", "message": "Provider not found"}

    safe_key = re.sub(r"[^A-Za-z0-9]", "", payload.name.upper())
    env_var_name = f"{safe_key}_API_KEY"

    providers[payload.name] = {
        "kind": payload.kind,
        "model": payload.model,
        "base_url": payload.base_url,
        "api_key": f"${{{env_var_name}}}",
        "temperature": payload.temperature,
        "max_tokens": payload.max_tokens,
    }
    # If name changed, remove old key
    if name != payload.name and name in providers:
        del providers[name]

    _save_config(cfg)
    if payload.api_key:
        _save_env({env_var_name: payload.api_key})
    load_env()
    return {"status": "ok"}


class TestProviderPayload(BaseModel):
    name: str


@app.post("/api/config/test")
async def test_provider(payload: TestProviderPayload) -> dict[str, Any]:
    """Send a minimal request to the provider to verify connectivity."""
    cfg = _load_config()
    providers = cfg.get("llm", {}).get("providers", {})
    name = payload.name
    if name not in providers:
        return {"status": "error", "message": f"供应商 \"{name}\" 不存在"}

    prov = providers[name]
    kind = prov.get("kind", "openai")
    model = prov.get("model", "")
    base_url = prov.get("base_url", "")
    api_key_env = prov.get("api_key", "")

    # Resolve API key
    resolved_key = ""
    if api_key_env.startswith("${") and api_key_env.endswith("}"):
        var_name = api_key_env[2:-1]
        import os
        resolved_key = os.getenv(var_name, "")
    elif api_key_env:
        resolved_key = api_key_env

    from cortexa.usage.context import annotate_usage
    from cortexa.usage.collector import UsageCallback
    from types import SimpleNamespace
    annotate_usage(action="provider_test")
    audit = UsageCallback(name, kind, model)
    audit_id = uuid.uuid4()
    if kind in ("openai", "anthropic", "ollama"):
        audit.on_chat_model_start(None, None, run_id=audit_id)

    def record_response(data):
        metadata = {"usage": data.get("usage"), "model": data.get("model"), "id": data.get("id")}
        if kind == "ollama":
            metadata["usage"] = {"input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")}
        message = SimpleNamespace(response_metadata=metadata)
        audit.finish(audit_id, SimpleNamespace(generations=[[SimpleNamespace(message=message)]]))

    try:
        if kind == "openai":
            import httpx
            url = (base_url.rstrip("/") if base_url else "https://api.openai.com/v1") + "/chat/completions"
            headers = {"Content-Type": "application/json"}
            if resolved_key:
                headers["Authorization"] = f"Bearer {resolved_key}"
            body = {
                "model": model,
                "messages": [{"role": "user", "content": "Hi, reply with just OK."}],
                "max_tokens": 10,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                record_response(data)
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"status": "ok", "message": f"连接成功！模型回复: {reply[:100]}"}

        elif kind == "anthropic":
            import httpx
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": resolved_key,
                "anthropic-version": "2023-06-01",
            }
            body = {
                "model": model,
                "messages": [{"role": "user", "content": "Hi, reply with just OK."}],
                "max_tokens": 10,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                record_response(data)
                reply = data.get("content", [{}])[0].get("text", "")
                return {"status": "ok", "message": f"连接成功！模型回复: {reply[:100]}"}

        elif kind == "ollama":
            import httpx
            url = (base_url or "http://localhost:11434") + "/api/chat"
            body = {
                "model": model,
                "messages": [{"role": "user", "content": "Hi, reply with just OK."}],
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
                record_response(data)
                reply = data.get("message", {}).get("content", "")
                return {"status": "ok", "message": f"连接成功！模型回复: {reply[:100]}"}

        else:
            return {"status": "error", "message": f"不支持的供应商类型: {kind}"}

    except asyncio.CancelledError as e:
        audit.on_llm_error(e, run_id=audit_id)
        raise
    except Exception as e:
        audit.on_llm_error(e, run_id=audit_id)
        return {"status": "error", "message": f"连接失败: {str(e)}"}


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------
class ChatPayload(BaseModel):
    message: str
    session_id: str = ""
    max_iterations: int = 2


@app.post("/api/chat")
async def chat(payload: ChatPayload) -> dict[str, Any]:
    sid = payload.session_id or str(uuid.uuid4())
    session = sessions.setdefault(sid, {"messages": [], "state": None})

    session["messages"].append({"role": "user", "content": payload.message})

    try:
        print(f"[chat] Received message: {payload.message}")
        graph = build_graph()
        goal = payload.message

        if session.get("state"):
            goal = session["state"].get("goal", payload.message)

        print(f"[chat] Invoking graph with goal: {goal[:50]}...")
        result: dict[str, object] = graph.invoke(
            {
                "goal": goal,
                "iterations": 0,
                "max_iterations": payload.max_iterations,
            }
        )

        draft = str(result.get("draft", ""))
        notes = str(result.get("notes", ""))
        session["state"] = result

        if draft:
            assistant_reply = (
                f"**研究笔记：**\n\n{notes}\n\n---\n\n**生成草稿：**\n\n{draft}"
            )
        else:
            assistant_reply = f"**研究笔记：**\n\n{notes}"

        session["messages"].append({"role": "assistant", "content": assistant_reply})

        print(f"[chat] Done. draft={len(draft)} chars, notes={len(notes)} chars")
        return {
            "session_id": sid,
            "reply": assistant_reply,
            "draft": draft,
            "notes": notes,
        }

    except Exception as exc:
        tb = traceback.format_exc()
        error_msg = f"❌ Agent 执行出错：{exc}"
        session["messages"].append({"role": "assistant", "content": error_msg})
        return {
            "session_id": sid,
            "reply": error_msg,
            "draft": "",
            "notes": "",
            "error": str(exc),
            "traceback": tb,
        }


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatPayload) -> StreamingResponse:
    async def event_generator():  # type: ignore[no-untyped-def]
        sid = payload.session_id or str(uuid.uuid4())
        session = sessions.setdefault(sid, {"messages": [], "state": None})
        session["messages"].append({"role": "user", "content": payload.message})
        yield f"data: {json.dumps({'type': 'start', 'session_id': sid})}\n\n"

        try:
            graph = build_graph()
            goal = payload.message
            if session.get("state"):
                goal = session["state"].get("goal", payload.message)

            for event in graph.stream(
                {
                    "goal": goal,
                    "iterations": 0,
                    "max_iterations": payload.max_iterations,
                },
                stream_mode="updates",
            ):
                for node_name, update in event.items():
                    update_data = {
                        k: str(v)[:200]
                        for k, v in update.items()
                        if k != "messages"
                    }
                    yield f"data: {json.dumps({'type': 'node', 'node': node_name, 'update': update_data})}\n\n"

            result = graph.invoke(
                {
                    "goal": goal,
                    "iterations": 0,
                    "max_iterations": payload.max_iterations,
                }
            )
            draft = str(result.get("draft", ""))
            notes = str(result.get("notes", ""))
            session["state"] = result

            if draft:
                reply = f"**研究笔记：**\n\n{notes}\n\n---\n\n**生成草稿：**\n\n{draft}"
            else:
                reply = f"**研究笔记：**\n\n{notes}"

            session["messages"].append({"role": "assistant", "content": reply})
            yield f"data: {json.dumps({'type': 'done', 'reply': reply, 'draft': draft, 'notes': notes})}\n\n"

        except Exception as exc:
            error_msg = f"❌ Agent 执行出错：{exc}"
            session["messages"].append({"role": "assistant", "content": error_msg})
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")  # type: ignore[no-untyped-call]


@app.get("/api/chat/history/{session_id}")
async def chat_history(session_id: str) -> dict[str, Any]:
    session = sessions.get(session_id, {"messages": []})
    return {"session_id": session_id, "messages": session["messages"]}


@app.post("/api/chat/clear/{session_id}")
async def chat_clear(session_id: str) -> dict[str, str]:
    sessions.pop(session_id, None)
    return {"status": "ok", "session_id": session_id}



# ---------------------------------------------------------------------------
# Vue SPA support
# ---------------------------------------------------------------------------
DIST_DIR = Path(__file__).parent / "static" / "dist"

@app.get("/{full_path:path}")
async def serve_vue(request: Request, full_path: str):
    """Serve Vue SPA for all non-API routes"""
    from fastapi.responses import FileResponse
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found")
    # Check if it's a static file in dist
    file_path = DIST_DIR / full_path
    if full_path and file_path.resolve().is_relative_to(DIST_DIR.resolve()) and file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    # Otherwise serve index.html for SPA routing (no-cache for SPA)
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    # Fallback to old template-based UI
    return templates.TemplateResponse("dashboard.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


@app.on_event("shutdown")
async def stop_memory_extraction():
    from cortexa.memory.integration import tasks
    pending=list(tasks)
    for task in pending:task.cancel()
    if pending:await asyncio.gather(*pending,return_exceptions=True)
