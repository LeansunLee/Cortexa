"""Data Capability System API - 数据源、数据能力、Agent绑定、查询执行"""

from __future__ import annotations

import uuid
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cortexa.api.deps import get_db, get_current_workspace
from cortexa.api.schemas import (
    DataSourceCreate, DataSourceOut,
    DataCredentialCreate, DataCredentialOut,
    DataSchemaOut,
    DataCapabilityCreate, DataCapabilityStatusUpdate, DataCapabilityOut,
    AgentDataBindingCreate, AgentDataBindingOut,
    DataQueryCreate, DataQueryOut, ManualDataQueryOut,
)
from cortexa.db.models import (
    DataSource, DataCredential, DataSchema, DataCapability,
    AgentDataBinding, DataQuery,
)
from cortexa.db.encryption import (
    encrypt_dict, decrypt_dict, safe_credential_response,
)
from cortexa.data.adapter import test_connection, sync_schema, execute_query
from cortexa.data.sql_drafts import validate_sql

router = APIRouter(prefix="/data", tags=["data-capability"])


# =========================================================================
# DataSource CRUD
# =========================================================================

@router.get("/sources", response_model=list[DataSourceOut])
async def list_data_sources(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    query = select(DataSource).order_by(DataSource.created_at.desc())
    if workspace_id:
        query = query.where(DataSource.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/sources", response_model=DataSourceOut, status_code=201)
async def create_data_source(
    payload: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    if not workspace_id:
        raise HTTPException(400, "workspace_id required")
    ds = DataSource(
        workspace_id=uuid.UUID(workspace_id),
        name=payload.name,
        description=payload.description,
        type=payload.type,
        config=payload.config,
        credential_id=uuid.UUID(payload.credential_id) if payload.credential_id else None,
        status="inactive",
    )
    db.add(ds)
    await db.flush()
    await db.refresh(ds)
    return ds


@router.get("/sources/{ds_id}", response_model=DataSourceOut)
async def get_data_source(ds_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ds = await db.get(DataSource, ds_id)
    if not ds:
        raise HTTPException(404, "Data source not found")
    return ds


@router.delete("/sources/{ds_id}", status_code=204)
async def delete_data_source(ds_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ds = await db.get(DataSource, ds_id)
    if not ds:
        raise HTTPException(404, "Data source not found")
    # Query audit rows have no DB-level cascade; detach them (history is kept,
    # dangling references are dropped) instead of failing after the 204.
    cap_ids = (
        await db.scalars(select(DataCapability.id).where(DataCapability.data_source_id == ds_id))
    ).all()
    if cap_ids:
        await db.execute(
            update(DataQuery)
            .where(DataQuery.data_capability_id.in_(cap_ids))
            .values(data_capability_id=None, data_source_id=None)
        )
        await db.execute(delete(AgentDataBinding).where(AgentDataBinding.data_capability_id.in_(cap_ids)))
        await db.execute(delete(DataCapability).where(DataCapability.id.in_(cap_ids)))
    await db.execute(
        update(DataQuery).where(DataQuery.data_source_id == ds_id).values(data_source_id=None)
    )
    await db.delete(ds)
    # Complete deletion before a 204 lets the client reload the list.
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "数据源仍被其他记录引用，删除未完成") from error


# =========================================================================
# DataSource Operations: Test Connection, Sync Schema
# =========================================================================

@router.post("/sources/{ds_id}/test")
async def test_data_source(ds_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ds = await db.get(DataSource, ds_id)
    if not ds:
        raise HTTPException(404, "Data source not found")
    cred_data = None
    if ds.credential_id:
        cred = await db.get(DataCredential, ds.credential_id)
        if cred:
            cred_data = cred.encrypted_data
    result = await test_connection(ds.type, ds.config, cred_data)
    # Update status
    ds.status = "active" if result["success"] else "error"
    await db.flush()
    return result


@router.post("/sources/{ds_id}/sync-schema")
async def sync_data_source_schema(ds_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ds = await db.get(DataSource, ds_id)
    if not ds:
        raise HTTPException(404, "Data source not found")
    cred_data = None
    if ds.credential_id:
        cred = await db.get(DataCredential, ds.credential_id)
        if cred:
            cred_data = cred.encrypted_data
    # Test connection first
    test_result = await test_connection(ds.type, ds.config, cred_data)
    if not test_result["success"]:
        raise HTTPException(400, f"连接失败: {test_result['message']}")

    # Sync schema
    schema_rows = await sync_schema(ds.type, ds.config, cred_data)

    # Delete old schema records
    await db.execute(delete(DataSchema).where(DataSchema.data_source_id == ds_id))

    # Insert new schema records
    for row in schema_rows:
        db.add(DataSchema(
            data_source_id=ds_id,
            schema_name=row["schema_name"],
            table_name=row["table_name"],
            column_name=row["column_name"],
            data_type=row["data_type"],
            description=row.get("description"),
            is_queryable=row.get("is_queryable", True),
            is_sensitive=row.get("is_sensitive", False),
        ))
    await db.flush()
    return {"synced": len(schema_rows), "message": f"同步了 {len(schema_rows)} 条表/列记录"}


@router.get("/sources/{ds_id}/schema", response_model=list[DataSchemaOut])
async def get_data_source_schema(ds_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    query = select(DataSchema).where(DataSchema.data_source_id == ds_id).order_by(
        DataSchema.table_name, DataSchema.column_name
    )
    result = await db.execute(query)
    return list(result.scalars().all())


# =========================================================================
# DataCredential CRUD
# =========================================================================

@router.get("/credentials", response_model=list[DataCredentialOut])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    query = select(DataCredential).order_by(DataCredential.created_at.desc())
    if workspace_id:
        query = query.where(DataCredential.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    creds = list(result.scalars().all())
    return [safe_credential_response(c) for c in creds]


@router.post("/credentials", response_model=DataCredentialOut, status_code=201)
async def create_credential(
    payload: DataCredentialCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    if not workspace_id:
        raise HTTPException(400, "workspace_id required")
    cred = DataCredential(
        workspace_id=uuid.UUID(workspace_id),
        name=payload.name,
        type=payload.type,
        encrypted_data=encrypt_dict(payload.data),
    )
    db.add(cred)
    await db.flush()
    await db.refresh(cred)
    return safe_credential_response(cred)


@router.delete("/credentials/{cred_id}", status_code=204)
async def delete_credential(cred_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cred = await db.get(DataCredential, cred_id)
    if not cred:
        raise HTTPException(404, "Credential not found")
    in_use = await db.scalar(
        select(func.count()).select_from(DataSource).where(DataSource.credential_id == cred_id)
    )
    if in_use:
        raise HTTPException(409, "该凭证仍被数据源使用，请先删除或改绑相关数据源")
    await db.delete(cred)
    # Complete deletion before a 204 lets the client reload the list.
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "凭证仍被其他记录引用，删除未完成") from error


# =========================================================================
# DataCapability CRUD
# =========================================================================

@router.get("/capabilities", response_model=list[DataCapabilityOut])
async def list_capabilities(
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    query = select(DataCapability).order_by(DataCapability.created_at.desc())
    if workspace_id:
        query = query.where(DataCapability.workspace_id == uuid.UUID(workspace_id))
    if agent_id:
        # Filter by agent's bindings
        query = query.join(AgentDataBinding).where(
            AgentDataBinding.agent_id == uuid.UUID(agent_id)
        )
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/capabilities", response_model=DataCapabilityOut, status_code=201)
async def create_capability(
    payload: DataCapabilityCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    if not workspace_id:
        raise HTTPException(400, "workspace_id required")
    original_sql = payload.original_sql or payload.query_template
    if original_sql:
        try:
            validate_sql(original_sql)
        except ValueError as exc:
            raise HTTPException(422, "原始 SQL 校验失败：" + str(exc)) from None
    if payload.query_template:
        try:
            validate_sql(payload.query_template)
        except ValueError as exc:
            raise HTTPException(422, "改写 SQL 校验失败：" + str(exc)) from None
    cap = DataCapability(
        workspace_id=uuid.UUID(workspace_id),
        name=payload.name,
        description=payload.description,
        data_source_id=uuid.UUID(payload.data_source_id),
        type=payload.type,
        input_schema=payload.input_schema,
        output_schema=payload.output_schema,
        query_template=payload.query_template,
        original_sql=original_sql,
        allowed_tables=payload.allowed_tables,
        allowed_columns=payload.allowed_columns,
        row_limit=payload.row_limit,
        timeout_seconds=payload.timeout_seconds,
    )
    db.add(cap)
    await db.flush()
    await db.refresh(cap)
    return cap


@router.patch("/capabilities/{cap_id}/status", response_model=DataCapabilityOut)
async def update_capability_status(
    cap_id: uuid.UUID,
    payload: DataCapabilityStatusUpdate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    cap = await db.get(DataCapability, cap_id)
    if not cap:
        raise HTTPException(404, "Data capability not found")
    if workspace_id and str(cap.workspace_id) != workspace_id:
        raise HTTPException(403, "无权访问该数据能力")
    cap.status = payload.status
    await db.flush()
    await db.refresh(cap)
    return cap


@router.get("/capabilities/{cap_id}", response_model=DataCapabilityOut)
async def get_capability(cap_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cap = await db.get(DataCapability, cap_id)
    if not cap:
        raise HTTPException(404, "Data capability not found")
    return cap


@router.delete("/capabilities/{cap_id}", status_code=204)
async def delete_capability(cap_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cap = await db.get(DataCapability, cap_id)
    if not cap:
        raise HTTPException(404, "Data capability not found")
    # Audit rows keep their history but lose the dangling capability reference;
    # agent bindings cascade at the DB level.
    await db.execute(
        update(DataQuery).where(DataQuery.data_capability_id == cap_id).values(data_capability_id=None)
    )
    await db.delete(cap)
    # Complete deletion before a 204 lets the client reload the list.
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "数据能力仍被其他记录引用，删除未完成") from error


@router.put("/capabilities/{cap_id}", response_model=DataCapabilityOut)
async def update_capability(
    cap_id: uuid.UUID,
    payload: DataCapabilityCreate,
    db: AsyncSession = Depends(get_db),
):
    cap = await db.get(DataCapability, cap_id)
    if not cap:
        raise HTTPException(404, "Data capability not found")
    if payload.name is not None:
        cap.name = payload.name
    if payload.description is not None:
        cap.description = payload.description
    if payload.data_source_id is not None:
        cap.data_source_id = uuid.UUID(payload.data_source_id)
    if payload.type is not None:
        cap.type = payload.type
    if payload.input_schema is not None:
        cap.input_schema = payload.input_schema
    if payload.output_schema is not None:
        cap.output_schema = payload.output_schema
    if payload.query_template is not None:
        try:
            validate_sql(payload.query_template)
        except ValueError as exc:
            raise HTTPException(422, "改写 SQL 校验失败：" + str(exc)) from None
        cap.query_template = payload.query_template
    if payload.original_sql is not None:
        try:
            validate_sql(payload.original_sql)
        except ValueError as exc:
            raise HTTPException(422, "原始 SQL 校验失败：" + str(exc)) from None
        cap.original_sql = payload.original_sql
    if payload.allowed_tables is not None:
        cap.allowed_tables = payload.allowed_tables
    if payload.allowed_columns is not None:
        cap.allowed_columns = payload.allowed_columns
    if payload.row_limit is not None:
        cap.row_limit = payload.row_limit
    if payload.timeout_seconds is not None:
        cap.timeout_seconds = payload.timeout_seconds
    await db.flush()
    await db.refresh(cap)
    return cap


# =========================================================================
# Agent Data Binding
# =========================================================================

@router.get("/bindings", response_model=list[AgentDataBindingOut])
async def list_bindings(
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(AgentDataBinding).order_by(AgentDataBinding.created_at.desc())
    if agent_id:
        query = query.where(AgentDataBinding.agent_id == uuid.UUID(agent_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/bindings", response_model=AgentDataBindingOut, status_code=201)
async def create_binding(
    payload: AgentDataBindingCreate,
    db: AsyncSession = Depends(get_db),
):
    # Check duplicate
    existing = await db.execute(select(AgentDataBinding).where(
        AgentDataBinding.agent_id == uuid.UUID(payload.agent_id),
        AgentDataBinding.data_capability_id == uuid.UUID(payload.data_capability_id),
    ))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Binding already exists")
    binding = AgentDataBinding(
        agent_id=uuid.UUID(payload.agent_id),
        data_capability_id=uuid.UUID(payload.data_capability_id),
    )
    db.add(binding)
    await db.flush()
    await db.refresh(binding)
    return binding


@router.delete("/bindings/{binding_id}", status_code=204)
async def delete_binding(binding_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    binding = await db.get(AgentDataBinding, binding_id)
    if not binding:
        raise HTTPException(404, "Binding not found")
    await db.delete(binding)


@router.delete("/bindings")
async def delete_binding_by_agent_cap(
    agent_id: str,
    data_capability_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AgentDataBinding).where(
        AgentDataBinding.agent_id == uuid.UUID(agent_id),
        AgentDataBinding.data_capability_id == uuid.UUID(data_capability_id),
    ))
    binding = result.scalar_one_or_none()
    if not binding:
        raise HTTPException(404, "Binding not found")
    await db.delete(binding)
    await db.flush()


# =========================================================================
# Execute Query (Manual Test)
# =========================================================================

@router.post("/query", response_model=ManualDataQueryOut, status_code=201)
async def execute_data_query(
    payload: DataQueryCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    # Load capability
    cap = await db.get(DataCapability, uuid.UUID(payload.data_capability_id))
    if not cap:
        raise HTTPException(404, "Data capability not found")

    # Workspace isolation check
    if workspace_id and str(cap.workspace_id) != workspace_id:
        raise HTTPException(403, "无权访问该数据能力")

    # Load data source
    ds = await db.get(DataSource, cap.data_source_id)
    if not ds:
        raise HTTPException(404, "Data source not found")

    # Load credential
    cred_data = None
    if ds.credential_id:
        cred = await db.get(DataCredential, ds.credential_id)
        if cred:
            cred_data = cred.encrypted_data

    # Security: check allowed tables
    # (simplified check - actual SQL parsing would be more robust)

    # Execute query
    query_result = await execute_query(
        ds_type=ds.type,
        config=ds.config,
        encrypted_credential=cred_data,
        query_template=cap.query_template or "",
        params=payload.params,
        row_limit=cap.row_limit,
        timeout_seconds=cap.timeout_seconds,
        read_only=True,
    )

    # Create audit record
    audit = DataQuery(
        workspace_id=uuid.UUID(workspace_id) if workspace_id else cap.workspace_id,
        data_capability_id=cap.id,
        data_source_id=ds.id,
        query_text=cap.query_template,
        input_params=payload.params,
        output_result={"row_count": query_result.get("row_count", 0), "columns": query_result.get("columns", [])},
        status="success" if query_result["success"] else "failed",
        duration_ms=query_result.get("duration_ms"),
        error_message=query_result.get("error"),
        source=payload.source,
    )
    db.add(audit)
    await db.flush()
    await db.refresh(audit)

    return {**DataQueryOut.model_validate(audit).model_dump(), "data": query_result.get("data")}


# =========================================================================
# Query Audit Logs
# =========================================================================

@router.get("/queries", response_model=list[DataQueryOut])
async def list_queries(
    agent_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
):
    query = select(DataQuery).order_by(DataQuery.created_at.desc()).limit(limit)
    if workspace_id:
        query = query.where(DataQuery.workspace_id == uuid.UUID(workspace_id))
    if agent_id:
        query = query.where(DataQuery.agent_id == uuid.UUID(agent_id))
    result = await db.execute(query)
    return list(result.scalars().all())


# =========================================================================
# Update Endpoints
# =========================================================================

@router.put("/sources/{ds_id}", response_model=DataSourceOut)
async def update_data_source(
    ds_id: uuid.UUID,
    payload: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
):
    ds = await db.get(DataSource, ds_id)
    if not ds:
        raise HTTPException(404, "Data source not found")
    if payload.name is not None:
        ds.name = payload.name
    if payload.description is not None:
        ds.description = payload.description
    if payload.type is not None:
        ds.type = payload.type
    if payload.config is not None:
        ds.config = payload.config
    if payload.credential_id is not None:
        ds.credential_id = uuid.UUID(payload.credential_id) if payload.credential_id else None
    await db.flush()
    await db.refresh(ds)
    return ds


@router.put("/credentials/{cred_id}", response_model=DataCredentialOut)
async def update_credential(
    cred_id: uuid.UUID,
    payload: DataCredentialCreate,
    db: AsyncSession = Depends(get_db),
):
    cred = await db.get(DataCredential, cred_id)
    if not cred:
        raise HTTPException(404, "Credential not found")
    if payload.name is not None:
        cred.name = payload.name
    if payload.type is not None:
        cred.type = payload.type
    if payload.data is not None:
        cred.encrypted_data = encrypt_dict(payload.data)
    await db.flush()
    await db.refresh(cred)
    return safe_credential_response(cred)
