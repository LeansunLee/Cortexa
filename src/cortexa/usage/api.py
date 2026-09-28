"""System-wide accounting endpoints. Every endpoint is explicitly superadmin-only."""

# ruff: noqa: B008 -- FastAPI dependency declarations
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import case, func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db
from cortexa.security.access import actor_required

from .collector import health
from .models import UsageCall as C
from .models import UsageOperation as O

SOURCES = {
    "conversation": "对话",
    "meeting": "会议",
    "agent_operations": "Agent 运维",
    "knowledge": "知识库",
    "work": "工作",
    "workflow": "工作流",
    "data_assistant": "数据助手",
    "memory": "记忆",
    "system": "系统任务",
    "configuration": "模型配置",
}
ACTIONS = {
    "embedding_index": "文档向量化",
    "embedding_query": "查询向量化",
    "retrieval_rewrite": "检索问题改写",
    "retrieval_hyde": "检索假设答案",
    "retrieval_context": "检索上下文补全",
    "provider_test": "供应商连接测试",
    "reply": "生成回复",
    "regenerate": "重新生成",
    "collaboration_execute": "协作 Agent 执行",
    "data_parameters": "数据工具参数解析",
    "proxy_prompt": "Proxy 提示词解析",
    "proxy_parameters": "Proxy 参数解析",
    "meeting_discussion": "会议讨论",
    "meeting_round_summary": "会议轮次总结",
    "meeting_conclusion": "会议结论",
    "meeting_todos": "会议待办提取",
    "document_summary": "文档摘要",
    "memory_extract": "记忆提取",
    "memory_summary": "记忆整理",
    "work_extract": "工作提取",
    "schema_generation": "输入结构生成",
    "sql_parameterize": "SQL 参数化",
    "workflow_execute": "工作流执行",
    "workflow_agent": "工作流 Agent",
    "research": "研究",
    "writing": "写作",
    "supervision": "审核",
    "model_call": "其他模型调用",
}
STATUS = {"running": "进行中", "success": "成功", "failed": "失败", "cancelled": "已取消", "interrupted": "进程中断"}


def select(*columns):
    return sa_select(*columns).execution_options(security_unscoped=True)


def require_usage_admin():
    actor = actor_required()
    if not actor.superadmin:
        raise HTTPException(403, "仅超级管理员可以查看模型用量")
    return actor


router = APIRouter(prefix="/admin/usage", tags=["Model usage"], dependencies=[Depends(require_usage_admin)])


class Filters:
    def __init__(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        workspace_id: str | None = Query(None, max_length=80),
        user_id: str | None = Query(None, max_length=80),
        agent_id: str | None = Query(None, max_length=80),
        source: str | None = Query(None, max_length=80),
        action: str | None = Query(None, max_length=80),
        provider: str | None = Query(None, max_length=160),
        model: str | None = Query(None, max_length=200),
        status: Literal["success", "failed", "cancelled", "interrupted", "running"] | None = None,
        usage_status: Literal["complete", "partial", "unknown"] | None = None,
        trigger: Literal["user", "background", "system"] | None = None,
        operation_id: uuid.UUID | None = None,
    ):
        end = end or datetime.now(UTC)
        start = start or end - timedelta(days=7)
        if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=366):
            raise HTTPException(422, "请选择带时区且不超过 366 天的有效时间范围")
        self.start, self.end = start, end
        self.conditions = [C.started_at >= start, C.started_at < end]
        for column, value in [
            (O.workspace_id, workspace_id),
            (O.user_id, user_id),
            (C.agent_id, agent_id),
            (O.source, source),
            (C.action, action),
            (C.provider, provider),
            (C.requested_model, model),
            (C.status, status),
            (C.usage_status, usage_status),
            (C.trigger, trigger),
            (C.operation_id, operation_id),
        ]:
            if value is not None:
                self.conditions.append(column.is_(None) if value == "__none__" else column == value)

    def query(self, *columns):
        return select(*columns).select_from(C).join(O, C.operation_id == O.id).where(*self.conditions)


def metrics():
    return [
        func.count(C.id).label("calls"),
        func.count(func.distinct(C.operation_id)).label("operations"),
        func.sum(C.input_tokens).label("input_tokens"),
        func.sum(C.output_tokens).label("output_tokens"),
        func.sum(C.total_tokens).label("total_tokens"),
        func.avg(C.total_tokens).label("avg_tokens"),
        func.count(case((C.usage_status == "complete", 1))).label("complete_calls"),
        func.count(case((C.usage_status == "unknown", 1))).label("unknown_calls"),
        func.count(case((C.status == "failed", 1))).label("failed_calls"),
        func.count(case((C.status.in_(["cancelled", "interrupted"]), 1))).label("interrupted_calls"),
        func.avg(C.duration_ms).label("avg_duration_ms"),
    ]


def stats(row):
    value = dict(row)
    calls = value.get("calls", 0)
    value["completeness"] = value.get("complete_calls", 0) / calls if calls else None
    if value.get("avg_duration_ms") is not None:
        value["avg_duration_ms"] = round(float(value["avg_duration_ms"]))
    if value.get("avg_tokens") is not None:
        value["avg_tokens"] = round(float(value["avg_tokens"]))
    return value


@router.get("/summary")
async def summary(f: Filters = Depends(), grain: Literal["day", "hour"] = "day", db: AsyncSession = Depends(get_db)):
    if grain == "hour" and f.end - f.start > timedelta(days=31):
        raise HTTPException(422, "按小时统计最多查询 31 天")
    totals = stats((await db.execute(f.query(*metrics()))).mappings().one())
    bucket = func.date_trunc(grain, func.timezone("Asia/Shanghai", C.started_at)).label("bucket")
    trend = []
    for row in (await db.execute(f.query(bucket, *metrics()).group_by(bucket).order_by(bucket))).mappings():
        value = stats(row)
        value["bucket"] = value["bucket"].replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()
        trend.append(value)
    return {"totals": totals, "trend": trend, "health": await health(), "start": f.start, "end": f.end}


GROUPS = {
    "source": (O.source, O.source),
    "action": (C.action, C.action),
    "model": (C.requested_model, C.requested_model),
    "provider": (C.provider, C.provider),
    "user": (O.user_id, O.user_name),
    "workspace": (O.workspace_id, O.workspace_id),
    "agent": (C.agent_id, C.agent_name),
}


@router.get("/groups")
async def groups(
    dimension: Literal["source", "action", "model", "provider", "user", "workspace", "agent"] = "source",
    f: Filters = Depends(),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    column, label = GROUPS[dimension]
    # Aggregate by stable ID; renames do not split a group.
    query = f.query(column.label("key"), func.max(label).label("label"), *metrics()).group_by(column)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(func.sum(C.total_tokens).desc().nullslast(), column)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).mappings()
    items = [stats(row) for row in rows]
    names = SOURCES if dimension == "source" else ACTIONS if dimension == "action" else {}
    for item in items:
        item["label"] = names.get(item["key"], item["label"]) or "系统 / 未归属"
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def call_columns():
    return [*C.__table__.columns, O.source, O.user_id, O.user_name, O.workspace_id, O.object_type, O.object_id]


@router.get("/calls")
async def calls(
    f: Filters = Depends(),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(f.query(func.count(C.id)))
    rows = (
        await db.execute(
            f.query(*call_columns()).order_by(C.started_at.desc(), C.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).mappings()
    return {"items": [dict(row) for row in rows], "total": count, "page": page, "page_size": page_size}


@router.get("/operations/{ident}")
async def operation(ident: uuid.UUID, page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db)):
    op = await db.get(O, ident, execution_options={"security_unscoped": True})
    if op is None:
        raise HTTPException(404, "用量操作不存在")
    f = select(C).where(C.operation_id == ident)
    count = await db.scalar(select(func.count()).select_from(f.subquery()))
    items = (await db.scalars(f.order_by(C.started_at, C.id).offset((page - 1) * 100).limit(100))).all()
    total = await db.scalar(select(func.sum(C.total_tokens)).where(C.operation_id == ident))
    return {
        "operation": {col.name: getattr(op, col.name) for col in O.__table__.columns},
        "items": [{col.name: getattr(c, col.name) for col in C.__table__.columns} for c in items],
        "total": count,
        "total_tokens": total,
        "page": page,
        "page_size": 100,
    }


@router.get("/options")
async def options(db: AsyncSession = Depends(get_db)):
    from cortexa.db.models import Workspace
    from cortexa.security.access import raw

    result = {"sources": SOURCES, "actions": ACTIONS, "statuses": STATUS}
    for key, col, label in [
        ("users", O.user_id, O.user_name),
        ("agents", C.agent_id, C.agent_name),
        ("providers", C.provider, C.provider),
        ("models", C.requested_model, C.requested_model),
    ]:
        query = (
            select(col.label("value"), func.max(label).label("label"))
            .where(col.is_not(None))
            .group_by(col)
            .order_by(col)
        )
        result[key] = [dict(row) for row in (await db.execute(query)).mappings()]
    result["workspaces"] = [
        {"value": str(w.id), "label": w.name}
        for w in (await db.scalars(raw(select(Workspace).order_by(Workspace.name)))).all()
    ]
    # Include deleted workspace IDs that still have an audit trail.
    known = {w["value"] for w in result["workspaces"]}
    for ident in (await db.scalars(select(O.workspace_id).where(O.workspace_id.is_not(None)).distinct())).all():
        if ident not in known:
            result["workspaces"].append({"value": ident, "label": ident + "（历史）"})
    return result


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value


@router.get("/export")
async def export(f: Filters = Depends(), db: AsyncSession = Depends(get_db)):
    count = await db.scalar(f.query(func.count(C.id)))
    if count > 50000:
        raise HTTPException(422, "单次最多导出 50,000 条，请缩小筛选范围")
    rows = (await db.execute(f.query(*call_columns()).order_by(C.started_at, C.id))).mappings()
    columns = {
        "id": "调用ID",
        "operation_id": "操作ID",
        "started_at": "时间(北京时间)",
        "source": "来源",
        "action": "动作",
        "user_name": "用户",
        "workspace_id": "空间ID",
        "agent_name": "Agent",
        "provider": "供应商",
        "requested_model": "请求模型",
        "actual_model": "返回模型",
        "input_tokens": "输入Token",
        "output_tokens": "输出Token",
        "total_tokens": "总Token",
        "cache_read_tokens": "缓存读取Token",
        "cache_creation_tokens": "缓存写入Token",
        "reasoning_tokens": "推理Token",
        "status": "执行状态",
        "usage_status": "用量状态",
        "duration_ms": "耗时ms",
        "retry_count": "可见重试次数",
        "object_id": "关联对象ID",
    }
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns.values())
    for row in rows:
        writer.writerow([csv_cell(row[key]) for key in columns])
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="model-usage.csv"', "Cache-Control": "no-store"},
    )
