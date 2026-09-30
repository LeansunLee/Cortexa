"""Agent CRUD + Version API."""

from __future__ import annotations
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db, get_current_workspace
from cortexa.api.schemas import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ModelProviderItem,
    ModelProviderListOut,
    AgentVersionCreate,
    AgentVersionOut,
    AgentRunCreate,
    AgentRunOut,
    ProxyInputResolutionRequest,
    AgentPublishRequest,
    AgentPublishResponse,
)
from cortexa.db.models import Agent, AgentVersion, AgentRun, Conversation, Workspace
from cortexa.runtime.policy import platform_config, resolve_effective_policy
from cortexa.runtime.state import BudgetLimits
from cortexa.security.access import actor_required, require

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentRuntimeBudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget: dict | None


async def runtime_budget_context(agent_id: uuid.UUID, db: AsyncSession, permission: str):
    require(permission)
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.workspace_id != actor_required().workspace_id:
        raise HTTPException(404, "Agent not found")
    workspace_policy = await db.scalar(select(Workspace.runtime_policy).where(Workspace.id == agent.workspace_id))
    config = platform_config()
    return agent, workspace_policy, config


def runtime_budget_response(agent, workspace_policy, config):
    inherited = resolve_effective_policy(config, workspace_policy)
    effective = resolve_effective_policy(config, workspace_policy, agent)
    return {
        "budget": ((agent.quality_policy or {}).get("runtime") or {}).get("budget"),
        "workspace_budget": inherited.effective_budget.model_dump(),
        "effective_budget": effective.effective_budget.model_dump(),
        "source_trace": effective.trace["budget"],
    }


def validate_goal_proxy(agent):
    if agent.agent_type == "proxy":
        from cortexa.runtime.proxy import validate_configuration
        try:
            validate_configuration(agent)
        except Exception:
            raise HTTPException(
                422,
                "目标模式 Proxy 契约无效：请声明静态 object 输入字段、字段类型和允许来源，"
                "并配置 GET/POST Endpoint",
            ) from None


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=list[AgentOut])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[Agent]:
    query = select(Agent).order_by(Agent.created_at.desc())
    if workspace_id:
        query = query.where(Agent.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Agent:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    # Use workspace default model if not specified
    model_name = payload.model
    if not model_name:
        ws = await db.get(Workspace, uuid.UUID(workspace_id))
        if ws and ws.default_model_provider:
            model_name = ws.default_model_provider

    agent = Agent(
        workspace_id=uuid.UUID(workspace_id),
        name=payload.name,
        collaboration=payload.collaboration.model_dump(mode="json"),
        description=payload.description,
        avatar=payload.avatar,
        agent_type=payload.agent_type,
        proxy_config=payload.proxy_config,
        role=(payload.role or "").strip() or None,
        personality=payload.personality,
        responsibilities=payload.responsibilities,
        boundaries=payload.boundaries,
        behavior=payload.behavior,
        model=model_name,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        system_prompt=payload.system_prompt,
        input_schema=payload.input_schema,
        output_schema=payload.output_schema,
        tags=payload.tags,
        knowledge_base_ids=[str(i) for i in payload.knowledge_base_ids],
        tool_ids=[str(i) for i in payload.tool_ids],
    )
    validate_goal_proxy(agent)
    if payload.web_search_enabled:
        from cortexa.tools.web_search import configure_search
        await configure_search(db, agent, True)
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


# ---------------------------------------------------------------------------
# Available Models (from config.yaml providers)
# ---------------------------------------------------------------------------
@router.get("/models/available", response_model=ModelProviderListOut)
async def list_available_models() -> ModelProviderListOut:
    """List all available model providers from config.yaml."""
    from cortexa.config.llm_providers import _load_yaml_config

    raw = _load_yaml_config()
    llm_block = raw.get("llm", {})
    providers = llm_block.get("providers", {})
    default_name = llm_block.get("default")

    items = []
    for name, prov in providers.items():
        items.append(ModelProviderItem(
            name=name,
            kind=prov.get("kind", "openai"),
            model=prov.get("model", ""),
            display_name=prov.get("display_name", name),
        ))

    return ModelProviderListOut(
        providers=items,
        default_provider=default_name,
    )



@router.get("/tools/web-search")
async def web_search_status() -> dict:
    from cortexa.tools.web_search import search_status
    return search_status()


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/{agent_id}/resources")
async def get_agent_resources(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    from cortexa.security.access import require
    from cortexa.api.agent_operations import resource_summary
    require("agent.read")
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return await resource_summary(agent, db)


@router.patch("/{agent_id}", response_model=AgentOut)
@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    update_data = payload.model_dump(exclude_unset=True)
    role = (update_data.get("role", agent.role) or "").strip()
    if not role:
        raise HTTPException(422, "业务角色不能为空")
    if "role" in update_data:
        update_data["role"] = role
    if "collaboration" in update_data:
        if payload.collaboration is None:
            raise HTTPException(422, "协作配置不能为 null")
        update_data["collaboration"] = {
            **(agent.collaboration or {}),
            **payload.collaboration.model_dump(mode="json", exclude_unset=True),
        }
    if "knowledge_base_ids" in update_data:
        update_data["knowledge_base_ids"] = [str(i) for i in update_data["knowledge_base_ids"]]
    if "tool_ids" in update_data:
        update_data["tool_ids"] = [str(i) for i in update_data["tool_ids"]]

    search_setting = update_data.pop("web_search_enabled", None)
    previous_tools = list(agent.tool_ids or [])
    if search_setting is not None:
        from cortexa.tools.web_search import configure_search
        agent.tool_ids = update_data.get("tool_ids", previous_tools)
        await configure_search(db, agent, search_setting)
        update_data["tool_ids"] = list(agent.tool_ids)
        agent.tool_ids = previous_tools

    requested_status = update_data.pop("status", None)
    if requested_status and requested_status not in (agent.status, "draft", "inactive", "archived"):
        raise HTTPException(422, "请通过发布操作启用 Agent")
    # Resource bindings are live operational settings, including on published Agents.
    # The dedicated agent-operations endpoints already apply them without unpublishing.
    changed = any(
        getattr(agent, field) != value
        for field, value in update_data.items()
        if field not in {"knowledge_base_ids", "tool_ids"}
    )
    for field, value in update_data.items():
        setattr(agent, field, value)
    validate_goal_proxy(agent)
    if changed:
        agent.status = "draft"
    elif requested_status:
        agent.status = requested_status
    await db.flush()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}/runtime-budget")
async def get_agent_runtime_budget(agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    agent, workspace_policy, config = await runtime_budget_context(agent_id, db, "agent.read")
    return runtime_budget_response(agent, workspace_policy, config)


@router.put("/{agent_id}/runtime-budget")
async def put_agent_runtime_budget(
    agent_id: uuid.UUID, payload: AgentRuntimeBudgetUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict:
    agent, workspace_policy, config = await runtime_budget_context(agent_id, db, "agent.update")
    inherited = resolve_effective_policy(config, workspace_policy).effective_budget.model_dump()
    if payload.budget is not None:
        try:
            validated_budget = BudgetLimits.model_validate(payload.budget)
        except ValueError:
            raise HTTPException(422, "Agent 运行预算格式或范围不合法") from None
        exceeded = [name for name in payload.budget if getattr(validated_budget, name) > inherited[name]]
        if exceeded:
            raise HTTPException(422, f"Agent 预算不能超过工作空间额度：{', '.join(exceeded)}")
    quality = dict(agent.quality_policy or {})
    runtime = dict(quality.get("runtime") or {})
    if payload.budget is None:
        runtime.pop("budget", None)
    else:
        runtime["budget"] = payload.budget
    if runtime:
        quality["runtime"] = runtime
    else:
        quality.pop("runtime", None)
    agent.quality_policy = quality
    await db.flush()
    return runtime_budget_response(agent, workspace_policy, config)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    from cortexa.db.models import Memory
    if await db.scalar(select(Memory.__table__.c.id).where(Memory.__table__.c.agent_id==agent.id).limit(1)):
        raise HTTPException(409,"此 Agent 有长期记忆，请先明确清理其记忆及派生关系")
    if await db.scalar(select(Conversation.id).where(Conversation.agent_id == agent.id).limit(1)):
        raise HTTPException(409, "此 Agent 有历史对话，请先处理对话再删除")
    await db.delete(agent)


# ---------------------------------------------------------------------------
# Agent Avatar Upload
# ---------------------------------------------------------------------------
UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads" / "avatars"

@router.post("/{agent_id}/avatar", response_model=AgentOut)
async def upload_avatar(
    agent_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Validate file type
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, GIF, WebP images are allowed")

    # Create upload dir
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Save file
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}[file.content_type]
    filename = f"{agent_id}.{ext}"
    filepath = UPLOAD_DIR / filename

    content_bytes = await file.read()
    if len(content_bytes) > 5 * 1024 * 1024:  # 5MB limit
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    filepath.write_bytes(content_bytes)

    # Update agent avatar URL
    avatar_url = f"/uploads/avatars/{filename}"
    agent.avatar = avatar_url
    await db.flush()
    await db.refresh(agent)
    return agent


# ---------------------------------------------------------------------------
# Agent Version
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/versions", response_model=list[AgentVersionOut])
async def list_versions(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[AgentVersion]:
    result = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
    )
    return list(result.scalars().all())


async def _create_version_impl(
    agent_id: uuid.UUID,
    release_notes: str | None,
    db: AsyncSession,
) -> AgentVersion:
    """Core version creation logic, shared by route handler and publish."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get next version number
    result = await db.execute(
        select(AgentVersion.version_number)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
        .limit(1)
    )
    last_version = result.scalar()
    next_version = (last_version or 0) + 1

    # Create snapshot of current agent state
    snapshot = {
        "name": agent.name,
        "collaboration": agent.collaboration,
        "description": agent.description,
        "agent_type": agent.agent_type,
        "proxy_config": agent.proxy_config,
        "role": agent.role,
        "personality": agent.personality,
        "responsibilities": agent.responsibilities,
        "boundaries": agent.boundaries,
        "behavior": agent.behavior,
        "model": agent.model,
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
        "system_prompt": agent.system_prompt,
        "input_schema": agent.input_schema,
        "output_schema": agent.output_schema,
        "tags": agent.tags,
        "knowledge_base_ids": agent.knowledge_base_ids,
        "tool_ids": agent.tool_ids,
    }

    version = AgentVersion(
        agent_id=agent_id,
        version_number=next_version,
        snapshot=snapshot,
        is_current=True,
        release_notes=release_notes,
    )

    # Mark previous versions as not current
    prev_versions = await db.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.is_current == True,
        )
    )
    for prev in prev_versions.scalars().all():
        prev.is_current = False

    # Update agent's current_version
    agent.current_version = next_version

    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


@router.post("/{agent_id}/versions", response_model=AgentVersionOut, status_code=201)
async def create_version(
    agent_id: uuid.UUID,
    payload: AgentVersionCreate,
    db: AsyncSession = Depends(get_db),
) -> AgentVersion:
    """Route handler for creating a version."""
    return await _create_version_impl(agent_id, payload.release_notes, db)


@router.get("/{agent_id}/versions/{version_id}", response_model=AgentVersionOut)
async def get_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AgentVersion:
    version = await db.get(AgentVersion, version_id)
    if not version or version.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


# ---------------------------------------------------------------------------
# Agent Publish
# ---------------------------------------------------------------------------
@router.post("/{agent_id}/publish", response_model=AgentPublishResponse)
async def publish_agent(
    agent_id: uuid.UUID,
    payload: AgentPublishRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentPublishResponse:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Validation
    errors = []
    if not agent.name:
        errors.append("Name is required")
    if not (agent.role or "").strip():
        errors.append("业务角色不能为空")
    if agent.input_schema is None:
        errors.append("Input Schema is required")
    if agent.output_schema is None:
        errors.append("Output Schema is required")
    if not agent.model:
        errors.append("Model is required")

    if errors:
        return AgentPublishResponse(success=False, errors=errors)

    # Snapshot current configuration on every publication.
    version_result = await _create_version_impl(agent_id, payload.release_notes, db)
    version_number = version_result.version_number

    # Publish current version
    result = await db.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.version_number == version_number,
        )
    )
    version = result.scalar_one_or_none()
    if version:
        version.is_published = True
        version.published_at = datetime.now(timezone.utc)

    # Update agent status
    agent.status = "active"

    await db.flush()

    return AgentPublishResponse(success=True, version_number=version_number)


# ---------------------------------------------------------------------------
# Agent Run History
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/runs", response_model=list[AgentRunOut])
async def list_runs(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[AgentRun]:
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.agent_id == agent_id)
        .order_by(AgentRun.created_at.desc())
        .limit(50)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Agent Test
# ---------------------------------------------------------------------------
@router.post("/{agent_id}/resolve-input")
async def resolve_proxy_agent_input(
    agent_id: uuid.UUID,
    payload: ProxyInputResolutionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Preview input resolution without calling the external Proxy endpoint."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.agent_type != "proxy":
        raise HTTPException(status_code=422, detail="仅 Proxy Agent 支持上下文解析测试")

    from types import SimpleNamespace

    from cortexa.agents.proxy_input_resolver import (
        prompt_resolution_enabled,
        resolve_proxy_input,
        resolve_proxy_prompt,
        system_resolution_values,
    )
    from cortexa.agents.proxy_executor import build_proxy_body

    preview_agent = SimpleNamespace(
        id=agent.id,
        workspace_id=agent.workspace_id,
        model=agent.model,
        input_schema=payload.input_schema if payload.input_schema is not None else agent.input_schema,
        proxy_config=payload.proxy_config if payload.proxy_config is not None else agent.proxy_config,
    )
    context = {
        "current_task": payload.task,
        "conversation_context": payload.conversation_context,
        "system": {**system_resolution_values(preview_agent), **payload.system},
        "previous_agent_output": payload.previous_agent_output,
    }
    if prompt_resolution_enabled(preview_agent):
        preview_input = dict(payload.explicit_input)
        preview_input.setdefault("input", payload.task)
        result = await resolve_proxy_prompt(preview_agent, preview_input, context)
        preview_supplemental_prompt = ""
    else:
        result = await resolve_proxy_input(preview_agent, payload.explicit_input, context)
        preview_supplemental_prompt = None
    result["requestBody"] = None
    if result["canInvoke"]:
        try:
            result["requestBody"] = build_proxy_body(
                preview_agent.proxy_config or {}, result["input"], preview_supplemental_prompt
            )
        except ValueError as error:
            result["canInvoke"] = False
            result["validationErrors"].append(str(error))
            result["message"] = str(error)
    return result


def _build_system_prompt(agent: Agent) -> str:
    """Build system prompt from agent configuration."""
    parts = []

    parts.append(f"你是{agent.role or 'AI助手'}。")

    if agent.personality:
        parts.append(f"\n## 人格特征\n{agent.personality}")

    if agent.responsibilities:
        parts.append(f"\n## 职责\n{agent.responsibilities}")

    if agent.boundaries:
        parts.append(f"\n## 工作边界\n{agent.boundaries}")

    if agent.behavior:
        parts.append(f"\n## 工作方式\n{agent.behavior}")

    if agent.system_prompt:
        parts.append(f"\n## 补充说明\n{agent.system_prompt}")

    if agent.output_schema:
        parts.append(f"\n## 输出格式要求\n请以JSON格式返回结果，包含以下字段：")
        for field, schema in agent.output_schema.get("properties", {}).items():
            desc = schema.get("description", "")
            parts.append(f"- {field}: {desc}")

    return "\n".join(parts) if parts else "你是一个AI助手。"


async def _retrieve_knowledge(agent, input_data: dict, db) -> str:
    """Retrieve relevant knowledge using RAG with public KB priority rule.

    Rule: When workspace public KBs and agent-specific KBs have conflicting
    content, the public KB results take priority.
    """
    from cortexa.rag.retriever import retrieve_with_priority

    kb_ids = agent.knowledge_base_ids or []
    if not kb_ids:
        return ""

    # Extract search query from input data
    query_text = ""
    if isinstance(input_data, dict):
        query_text = input_data.get("query", "") or input_data.get("question", "") or input_data.get("input", "")
        if not query_text:
            query_text = json.dumps(input_data, ensure_ascii=False)
    else:
        query_text = str(input_data)

    if not query_text.strip():
        return ""

    # Retrieval with public KB priority
    try:
        results = await retrieve_with_priority(
            db, kb_ids, query_text, top_k=5, min_score=0.3
        )
    except Exception as e:
        print(f"[RAG] Priority retrieval failed, falling back to keyword: {e}")
        return await _fallback_keyword_retrieval(agent, input_data, db)

    if not results:
        # Fallback to keyword if no results
        return await _fallback_keyword_retrieval(agent, input_data, db)

    context_parts = []
    for r in results:
        kb_type = (r.metadata or {}).get("kb_type", "unknown")
        kb_label = "公共知识库" if kb_type == "public" else "Agent知识库"
        context_parts.append(
            f"### {r.document_name} [{kb_label}] (相关度: {r.score:.2f})\n{r.content[:1500]}"
        )

    return "\n\n".join(context_parts)


async def _fallback_keyword_retrieval(agent, input_data: dict, db) -> str:
    """Fallback keyword-based retrieval when vector search returns no results."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from sqlalchemy import or_
    from cortexa.db.models import Document, KnowledgeBase

    kb_ids = agent.knowledge_base_ids or []
    query_text = ""
    if isinstance(input_data, dict):
        query_text = input_data.get("query", "") or input_data.get("question", "") or input_data.get("input", "")
        if not query_text:
            query_text = json.dumps(input_data, ensure_ascii=False)
    else:
        query_text = str(input_data)

    if not query_text.strip():
        return ""

    all_docs = []
    for kb_id_str in kb_ids:
        try:
            kid = uuid.UUID(kb_id_str)
            query = select(Document).join(
                KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id
            ).where(
                Document.knowledge_base_id == kid,
                KnowledgeBase.status == "active",
                Document.status == "active",
                or_(
                    Document.valid_until.is_(None),
                    Document.valid_until >= datetime.now(ZoneInfo("Asia/Shanghai")).date(),
                ),
            )
            result = await db.execute(query)
            all_docs.extend(result.scalars().all())
        except Exception:
            continue

    if not all_docs:
        return ""

    query_lower = query_text.lower()
    keywords = set(query_lower.split())

    scored = []
    for doc in all_docs:
        if not doc.content:
            continue
        content_lower = doc.content.lower()
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_docs = scored[:5] if scored else [(0, doc) for doc in all_docs[:3]]

    context_parts = []
    for _, doc in top_docs:
        content_preview = doc.content[:1500] if len(doc.content) > 1500 else doc.content
        context_parts.append(f"### {doc.name}\n{content_preview}")

    return "\n\n".join(context_parts)


def _validate_output(data: dict, schema: dict) -> list[str]:
    """Validate output against JSON Schema."""
    errors = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    return errors
