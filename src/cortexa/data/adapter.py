"""Database Adapter - 异步连接外部数据库执行查询"""

from __future__ import annotations

import json
import secrets
import time
import traceback
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

from cortexa.db.encryption import decrypt_dict


def _build_connection_url(ds_type: str, config: dict, credential_data: dict | None) -> URL:
    """Build async connection URL from config + credential."""
    host = config.get("host", "localhost")
    port = config.get("port", 5432 if ds_type == "postgres" else 3306)
    database = config.get("database", "")
    username = credential_data.get("username", "") if credential_data else ""
    password = credential_data.get("password", "") if credential_data else ""

    if ds_type == "postgres":
        return URL.create("postgresql+asyncpg", username=username, password=password, host=host, port=int(port), database=database)
    elif ds_type == "mysql":
        return URL.create("mysql+aiomysql", username=username, password=password, host=host, port=int(port), database=database)
    else:
        raise ValueError(f"Unsupported data source type: {ds_type}")


async def test_connection(ds_type: str, config: dict, encrypted_credential: str | None) -> dict:
    """Test database connection. Returns {success, message}."""
    credential_data = None
    if encrypted_credential:
        try:
            credential_data = decrypt_dict(encrypted_credential)
        except Exception as e:
            return {"success": False, "message": f"凭证解密失败: {e}"}

    url = _build_connection_url(ds_type, config, credential_data)
    engine: AsyncEngine | None = None
    try:
        engine = create_async_engine(url, pool_pre_ping=True, pool_size=1)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.scalar()
        if ds_type == "postgres" and credential_data and credential_data.get("password"):
            # A local PostgreSQL trust rule can accept any password. In that case
            # the connection works, but the supplied credential has not been tested.
            invalid = {**credential_data, "password": secrets.token_urlsafe(32)}
            probe = create_async_engine(_build_connection_url(ds_type, config, invalid), pool_size=1)
            try:
                async with probe.connect():
                    return {"success": False, "message": "数据库未校验密码，无法验证此凭证；请调整数据库认证规则"}
            except Exception as error:
                if "password authentication failed" not in str(error).lower() and "invalidpassword" not in type(error).__name__.lower():
                    return {"success": False, "message": "无法确认数据库是否校验密码，凭证测试未通过"}
            finally:
                await probe.dispose()
        return {"success": True, "message": "连接成功"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {e}"}
    finally:
        if engine:
            await engine.dispose()


async def sync_schema(ds_type: str, config: dict, encrypted_credential: str | None) -> list[dict]:
    """Sync database schema, return list of table/column metadata."""
    credential_data = None
    if encrypted_credential:
        credential_data = decrypt_dict(encrypted_credential)

    url = _build_connection_url(ds_type, config, credential_data)
    engine = create_async_engine(url, pool_size=1)
    tables: list[dict] = []

    try:
        async with engine.connect() as conn:
            if ds_type == "postgres":
                query = text("""
                    SELECT table_schema, table_name, column_name, data_type,
                           is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY table_schema, table_name, ordinal_position
                """)
            elif ds_type == "mysql":
                query = text("""
                    SELECT TABLE_SCHEMA as table_schema, TABLE_NAME as table_name,
                           COLUMN_NAME as column_name, DATA_TYPE as data_type,
                           IS_NULLABLE as is_nullable, COLUMN_DEFAULT as column_default
                    FROM information_schema.columns
                    WHERE TABLE_SCHEMA = :db_name
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                """, {"db_name": config.get("database", "")})
            else:
                return []

            result = await conn.execute(query)
            for row in result:
                tables.append({
                    "schema_name": row[0] or "public",
                    "table_name": row[1],
                    "column_name": row[2],
                    "data_type": row[3],
                    "description": None,
                    "is_queryable": True,
                    "is_sensitive": False,
                })
    finally:
        await engine.dispose()

    return tables


async def execute_query(
    ds_type: str,
    config: dict,
    encrypted_credential: str | None,
    query_template: str,
    params: dict,
    row_limit: int = 1000,
    timeout_seconds: int = 30,
    read_only: bool = False,
) -> dict:
    """Execute a parameterized query. Returns {success, data, duration_ms, row_count, error}."""
    if read_only:
        from cortexa.data.sql_drafts import validate_sql
        query_template, _ = validate_sql(query_template)
    credential_data = None
    if encrypted_credential:
        credential_data = decrypt_dict(encrypted_credential)

    url = _build_connection_url(ds_type, config, credential_data)
    # Set statement timeout via connect_args
    connect_args = {}
    if ds_type == "postgres":
        connect_args["server_settings"] = {"statement_timeout": f"{timeout_seconds * 1000}"}

    engine = create_async_engine(url, pool_size=1, connect_args=connect_args)
    start = time.time()

    try:
        async with engine.connect() as conn:
            if read_only:
                # Reuse SQL draft protection; validation alone cannot stop mutating functions.
                if ds_type == "postgres":
                    await conn.execute(text("SET TRANSACTION READ ONLY"))
                else:
                    await conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
                    await conn.commit()
            # Apply row limit if not already in query
            exec_sql = query_template
            if "LIMIT" not in query_template.upper():
                exec_sql = f"{query_template.rstrip().rstrip(';')} LIMIT {row_limit}"

            result = await conn.execute(text(exec_sql), params)
            columns = list(result.keys()) if result.returns_rows else []
            rows = result.fetchmany(row_limit) if result.returns_rows else []
            data = [dict(zip(columns, row)) for row in rows]
            duration_ms = int((time.time() - start) * 1000)

            return {
                "success": True,
                "data": data,
                "duration_ms": duration_ms,
                "row_count": len(data),
                "columns": columns,
                "error": None,
            }
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "success": False,
            "data": None,
            "duration_ms": duration_ms,
            "row_count": 0,
            "columns": [],
            "error": str(e),
        }
    finally:
        await engine.dispose()
