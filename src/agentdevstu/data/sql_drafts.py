"""Read-only, bounded execution for unsaved SQL drafts."""

import asyncio
import re
import time

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from agentdevstu.db.encryption import decrypt_dict

# Mask strings, quoted identifiers and comments before classifying statements.
TOKENS = re.compile(
    r"'(?:(?:'')|(?:\\.)|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|--[^\n]*|/\*[\s\S]*?\*/|\$(?P<tag>[A-Za-z_][A-Za-z0-9_]*|)\$[\s\S]*?\$(?P=tag)\$"
)
PARAMETER = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


def validate_sql(sql):
    sql = sql.strip().rstrip(";").strip()
    if "/*!" in sql:
        raise ValueError("不支持可执行 SQL 注释")
    masked = TOKENS.sub(lambda m: " " * len(m.group()), sql)
    if not re.match(r"^\s*(SELECT|WITH)\b", masked, re.I) or ";" in masked:
        raise ValueError("仅支持一条 SELECT 或 WITH 查询")
    if re.search(
        r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|CALL|EXECUTE|COPY|INTO|LOCK|SET)\b",
        masked,
        re.I,
    ):
        raise ValueError("仅支持只读查询，不支持写入、锁定或管理语句")
    if any(c in masked for c in ("'", '"', "`")) or "/*" in masked:
        raise ValueError("SQL 引号或注释未闭合")
    parameters = list(dict.fromkeys(PARAMETER.findall(masked)))
    if set(parameters) != set(PARAMETER.findall(sql)):
        raise ValueError("请移除注释或字符串中形似 :参数名 的文本，避免与查询参数混淆")
    if len(parameters) > 60:
        raise ValueError("参数不得超过 60 个")
    return sql, parameters


async def execute_draft(source, encrypted, sql, params):
    credentials = decrypt_dict(encrypted) if encrypted else {}
    url = URL.create(
        "postgresql+asyncpg" if source.type == "postgres" else "mysql+aiomysql",
        username=credentials.get("username") or None,
        password=credentials.get("password") or None,
        host=source.config.get("host", "localhost"),
        port=int(source.config.get("port", 5432 if source.type == "postgres" else 3306)),
        database=source.config.get("database", ""),
    )
    options = {"server_settings": {"statement_timeout": "10000"}} if source.type == "postgres" else {}
    engine = create_async_engine(url, pool_size=1, max_overflow=0, connect_args=options)
    started = time.monotonic()
    try:
        async with asyncio.timeout(15):
            async with engine.connect() as conn:
                # Backend transaction protection is mandatory even after SQL classification.
                if source.type == "postgres":
                    await conn.execute(text("SET TRANSACTION READ ONLY"))
                else:
                    await conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
                    await conn.commit()
                result = await conn.execute(text(f"SELECT * FROM (\n{sql}\n) AS draft_preview LIMIT 51"), params)
                columns = list(result.keys())
                rows = result.fetchmany(51)
                # Rows stay arrays so duplicate SQL column names cannot silently overwrite values.
                output = {
                    "success": True,
                    "columns": columns,
                    "rows": [list(r) for r in rows[:50]],
                    "row_count": min(len(rows), 50),
                    "truncated": len(rows) > 50,
                    "error": None,
                }
                await conn.rollback()
    except TimeoutError:
        output = {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "error": "试运行超时，请缩小查询范围后重试",
        }
    except Exception as exc:
        # Driver message only; do not expose connection URLs, SQLAlchemy parameters or tracebacks.
        message = str(getattr(exc, "orig", exc)).split("\n")[0][:500]
        if credentials.get("password"):
            message = message.replace(credentials["password"], "***")
        output = {"success": False, "columns": [], "rows": [], "row_count": 0, "truncated": False, "error": message}
    finally:
        await engine.dispose()
    output["duration_ms"] = round((time.monotonic() - started) * 1000)
    return output
