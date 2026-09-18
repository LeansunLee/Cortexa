"""Meeting-specific LangChain Tools — knowledge search & data query for agent turns.

Each tool is a lightweight wrapper that captures the agent context at creation
time and delegates to the existing RAG / data-capability infrastructure.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.tools import tool

from agentdevstu.db.engine import async_session_factory


# ---------------------------------------------------------------------------
# knowledge_search — search agent-bound knowledge bases
# ---------------------------------------------------------------------------

@tool
async def knowledge_search(query: str, top_k: int = 5) -> str:
    """Search your bound knowledge bases for information relevant to the meeting topic.

    Use this when you need factual background, past decisions, documentation,
    or domain-specific knowledge to support your analysis. The query should
    describe what information you are looking for.

    Args:
        query: A clear description of the information you need.
        top_k: Number of results to return (default 5, max 10).

    Returns:
        A JSON string containing the search results, or an error message.
    """
    # The actual implementation is injected at tool-creation time via a closure.
    # This stub is replaced by _make_knowledge_search_tool().
    return '{"error": "Tool not properly initialized"}'


@tool
async def data_query(capability_name: str, params: str = "{}") -> str:
    """Execute a data query through one of your bound data capabilities.

    Use this when you need real-time business data (sales, orders, metrics,
    etc.) to support your analysis. Each data capability has a predefined
    query template — you only need to provide the capability name and
    any required parameters.

    Args:
        capability_name: The name of the data capability to use (e.g. "月度销售额查询").
        params: A JSON string of parameters for the query (default "{}").
                Check the capability's input_schema for required parameters.

    Returns:
        A JSON string containing the query results, or an error message.
    """
    return '{"error": "Tool not properly initialized"}'


# ---------------------------------------------------------------------------
# Factory: create bound tools for a specific agent in a meeting
# ---------------------------------------------------------------------------

class MeetingToolProvider:
    """Creates LangChain tools bound to a specific agent's capabilities.

    Usage in meeting runtime:
        provider = MeetingToolProvider(agent, workspace_id)
        tools = provider.get_tools()
        if tools:
            model_with_tools = llm.bind_tools(tools)
            # ... tool-calling loop ...
    """

    def __init__(
        self,
        agent_id: uuid.UUID,
        knowledge_base_ids: list[str],
        tool_ids: list[str],
        workspace_id: uuid.UUID,
    ):
        self.agent_id = agent_id
        self.knowledge_base_ids = knowledge_base_ids or []
        self.tool_ids = tool_ids or []
        self.workspace_id = workspace_id
        self._tools: list = []
        self._build()

    def _build(self) -> None:
        if self.knowledge_base_ids:
            self._tools.append(self._make_knowledge_search_tool())
        if self.tool_ids:
            self._tools.append(self._make_data_query_tool())

    def get_tools(self) -> list:
        return self._tools

    def has_tools(self) -> bool:
        return len(self._tools) > 0

    # ---- knowledge search tool (closure-based) ----

    def _make_knowledge_search_tool(self):
        kb_ids = list(self.knowledge_base_ids)
        agent_id = self.agent_id

        @tool
        async def _knowledge_search(query: str, top_k: int = 5) -> str:
            """Search your bound knowledge bases for information relevant to the meeting topic.

            Use this when you need factual background, past decisions, documentation,
            or domain-specific knowledge to support your analysis.

            Args:
                query: A clear description of the information you need.
                top_k: Number of results to return (default 5, max 10).

            Returns:
                A JSON string containing search results with content and scores.
            """
            top_k = min(max(top_k, 1), 10)
            try:
                async with async_session_factory() as db:
                    from agentdevstu.rag.retriever import retrieve_relevant_chunks

                    results = await retrieve_relevant_chunks(
                        db=db,
                        knowledge_base_ids=kb_ids,
                        query_text=query,
                        top_k=top_k,
                        min_score=0.1,
                        strategy="bm25",
                    )
                    if not results:
                        return json.dumps(
                            {"results": [], "message": "未找到相关知识"}, ensure_ascii=False
                        )
                    items = [
                        {
                            "document_name": r.document_name,
                            "content": r.content[:1500],
                            "score": round(r.score, 3),
                        }
                        for r in results
                    ]
                    return json.dumps({"results": items}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        _knowledge_search.name = "knowledge_search"
        return _knowledge_search

    # ---- data query tool (closure-based) ----

    def _make_data_query_tool(self):
        tool_ids = list(self.tool_ids)
        ws_id = self.workspace_id

        @tool
        async def _data_query(capability_name: str, params: str = "{}") -> str:
            """Execute a data query through one of your bound data capabilities.

            Use this when you need real-time business data to support your analysis.

            Args:
                capability_name: The name of the data capability (e.g. "月度销售额查询").
                params: A JSON string of parameters for the query (default "{}").

            Returns:
                A JSON string containing the query results.
            """
            try:
                params_dict = json.loads(params) if params else {}
            except json.JSONDecodeError:
                params_dict = {}

            try:
                async with async_session_factory() as db:
                    from sqlalchemy import select
                    from agentdevstu.db.models import (
                        DataCapability, DataSource, DataCredential, DataQuery,
                    )
                    from agentdevstu.data.adapter import execute_query
                    from agentdevstu.db.encryption import decrypt_dict

                    # Find the matching capability
                    caps_result = await db.execute(
                        select(DataCapability).where(
                            DataCapability.id.in_([uuid.UUID(tid) for tid in tool_ids])
                        )
                    )
                    capabilities = {c.name: c for c in caps_result.scalars().all()}

                    cap = capabilities.get(capability_name)
                    if not cap:
                        available = list(capabilities.keys())
                        return json.dumps(
                            {
                                "error": f"未找到名为 '{capability_name}' 的数据能力",
                                "available_capabilities": available,
                            },
                            ensure_ascii=False,
                        )

                    # Get data source and credential
                    ds = await db.get(DataSource, cap.data_source_id)
                    if not ds:
                        return json.dumps({"error": "数据源不存在"}, ensure_ascii=False)

                    cred_data = None
                    if ds.credential_id:
                        cred = await db.get(DataCredential, ds.credential_id)
                        if cred and cred.encrypted_data:
                            cred_data = decrypt_dict(cred.encrypted_data)

                    if not cap.query_template:
                        return json.dumps(
                            {"error": "该数据能力未配置查询模板"}, ensure_ascii=False
                        )

                    # Execute query
                    result = await execute_query(
                        ds_type=ds.type,
                        config=ds.config,
                        encrypted_credential=None,  # already decrypted
                        query_template=cap.query_template,
                        params=params_dict,
                        row_limit=cap.row_limit,
                        timeout_seconds=cap.timeout_seconds,
                    )

                    # Build response with credential handling
                    # Re-execute with decrypted credential
                    if cred_data and not result.get("success"):
                        url_parts = []
                        if ds.type == "postgres":
                            host = ds.config.get("host", "localhost")
                            port = ds.config.get("port", 5432)
                            db_name = ds.config.get("database", "")
                            username = cred_data.get("username", "")
                            password = cred_data.get("password", "")
                            url = f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{db_name}"
                        elif ds.type == "mysql":
                            host = ds.config.get("host", "localhost")
                            port = ds.config.get("port", 3306)
                            db_name = ds.config.get("database", "")
                            username = cred_data.get("username", "")
                            password = cred_data.get("password", "")
                            url = f"mysql+aiomysql://{username}:{password}@{host}:{port}/{db_name}"
                        else:
                            return json.dumps(
                                {"error": f"不支持的数据源类型: {ds.type}"},
                                ensure_ascii=False,
                            )

                        from sqlalchemy.ext.asyncio import create_async_engine
                        from sqlalchemy import text
                        import time

                        connect_args = {}
                        if ds.type == "postgres":
                            connect_args["server_settings"] = {
                                "statement_timeout": f"{cap.timeout_seconds * 1000}"
                            }

                        engine = create_async_engine(url, pool_size=1, connect_args=connect_args)
                        try:
                            start = time.time()
                            async with engine.connect() as conn:
                                exec_sql = cap.query_template
                                if "LIMIT" not in cap.query_template.upper():
                                    exec_sql = f"{cap.query_template.rstrip().rstrip(';')} LIMIT {cap.row_limit}"
                                sql_result = await conn.execute(text(exec_sql), params_dict)
                                columns = list(sql_result.keys()) if sql_result.returns_rows else []
                                rows = sql_result.fetchmany(cap.row_limit) if sql_result.returns_rows else []
                                data = [dict(zip(columns, row)) for row in rows]
                                duration_ms = int((time.time() - start) * 1000)
                                result = {
                                    "success": True,
                                    "data": data[:50],
                                    "duration_ms": duration_ms,
                                    "row_count": len(data),
                                    "columns": columns,
                                }
                        finally:
                            await engine.dispose()

                    # Audit log
                    try:
                        from agentdevstu.db.models import DataQuery
                        audit = DataQuery(
                            workspace_id=ws_id,
                            agent_id=self.agent_id,
                            data_capability_id=cap.id,
                            data_source_id=cap.data_source_id,
                            query_text=cap.query_template[:500] if cap.query_template else None,
                            input_params=params_dict,
                            output_result={"row_count": result.get("row_count", 0)} if result.get("success") else None,
                            status="success" if result.get("success") else "failed",
                            duration_ms=result.get("duration_ms"),
                            error_message=result.get("error"),
                            source="meeting",
                        )
                        db.add(audit)
                        await db.flush()
                    except Exception:
                        pass

                    # Format response
                    if result.get("success"):
                        return json.dumps(
                            {
                                "data": result.get("data", [])[:30],
                                "row_count": result.get("row_count", 0),
                                "duration_ms": result.get("duration_ms", 0),
                            },
                            ensure_ascii=False,
                        )
                    else:
                        return json.dumps(
                            {"error": result.get("error", "查询失败")},
                            ensure_ascii=False,
                        )
            except Exception as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        _data_query.name = "data_query"
        return _data_query
