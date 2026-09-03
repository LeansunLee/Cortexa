"""Agent CRUD + Version + Test API."""

from __future__ import annotations

import json
import time
import traceback
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.api.schemas import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ModelProviderItem,
    ModelProviderListOut,
    AgentVersionCreate,
    AgentVersionOut,
    AgentRunCreate,
    AgentRunOut,
    AgentTestRequest,
    AgentTestResponse,
    AgentPublishRequest,
    AgentPublishResponse,
)
from agentdevstu.db.models import Agent, AgentVersion, AgentRun, Workspace

router = APIRouter(prefix="/agents", tags=["agents"])


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
        description=payload.description,
        avatar=payload.avatar,
        agent_type=payload.agent_type,
        proxy_config=payload.proxy_config,
        role=payload.role,
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
    from agentdevstu.config.llm_providers import _load_yaml_config
    
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



@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


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
    if "knowledge_base_ids" in update_data:
        update_data["knowledge_base_ids"] = [str(i) for i in update_data["knowledge_base_ids"]]
    if "tool_ids" in update_data:
        update_data["tool_ids"] = [str(i) for i in update_data["tool_ids"]]
    
    for field, value in update_data.items():
        setattr(agent, field, value)
    
    await db.flush()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
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
    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "png"
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
        "description": agent.description,
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
    if agent.input_schema is None:
        errors.append("Input Schema is required")
    if agent.output_schema is None:
        errors.append("Output Schema is required")
    if not agent.model:
        errors.append("Model is required")
    
    if errors:
        return AgentPublishResponse(success=False, errors=errors)
    
    # Create version if needed
    if agent.current_version == 0:
        version_result = await _create_version_impl(agent_id, payload.release_notes, db)
        version_number = version_result.version_number
    else:
        version_number = agent.current_version
    
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
@router.post("/{agent_id}/test", response_model=AgentTestResponse)
async def test_agent(
    agent_id: uuid.UUID,
    payload: AgentTestRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentTestResponse:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Dispatch by agent type
    if agent.agent_type == "proxy":
        from agentdevstu.agents.proxy_executor import execute_proxy_agent
        result = await execute_proxy_agent(agent, payload.input_data, db)
        return AgentTestResponse(
            success=result["success"],
            output_data=result.get("output_data"),
            error=result.get("error"),
            duration_ms=result.get("duration_ms", 0),
        )
    
    # Default: LLM agent
    start_time = time.time()
    
    ver_result = await db.execute(
        select(AgentVersion.id).where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc()).limit(1)
    )
    version_id = ver_result.scalar() or uuid.uuid4()
    
    try:
        from agentdevstu.config.llm_providers import create_llm
        
        model = create_llm(agent.model)
        system_prompt = _build_system_prompt(agent)
        user_message = json.dumps(payload.input_data, ensure_ascii=False, indent=2)
        
        response = model.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ])
        
        output_text = response.content if hasattr(response, 'content') else str(response)
        
        try:
            output_data = json.loads(output_text)
        except json.JSONDecodeError:
            output_data = {"response": output_text}
        
        if agent.output_schema:
            validation_errors = _validate_output(output_data, agent.output_schema)
            if validation_errors:
                output_data["_validation_errors"] = validation_errors
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        run = AgentRun(
            agent_id=agent_id,
            agent_version_id=version_id,
            input_data=payload.input_data,
            output_data=output_data,
            status="completed",
            duration_ms=duration_ms,
        )
        db.add(run)
        await db.flush()
        
        return AgentTestResponse(
            success=True,
            output_data=output_data,
            duration_ms=duration_ms,
        )
    
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        error_msg = str(e)
        
        run = AgentRun(
            agent_id=agent_id,
            agent_version_id=version_id,
            input_data=payload.input_data,
            status="failed",
            error_message=error_msg,
            duration_ms=duration_ms,
        )
        db.add(run)
        await db.flush()
        
        return AgentTestResponse(
            success=False,
            error=error_msg,
            duration_ms=duration_ms,
        )


def _build_system_prompt(agent: Agent) -> str:
    """Build system prompt from agent configuration."""
    parts = []
    
    if agent.name:
        parts.append(f"你是{agent.name}。")
    
    if agent.personality:
        parts.append(f"\n## 人格特征\n{agent.personality}")
    
    if agent.role:
        parts.append(f"\n## 角色\n{agent.role}")
    
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


def _validate_output(data: dict, schema: dict) -> list[str]:
    """Validate output against JSON Schema."""
    errors = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")
    
    return errors
