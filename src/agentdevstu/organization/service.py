"""Workspace-scoped directory and explainable human assignee ranking."""

import json
import re
from collections import Counter

import jieba
from sqlalchemy import and_, select

from agentdevstu.organization.models import MemberProfile, OrgUnit
from agentdevstu.security.models import Membership, User
from agentdevstu.work.models import Work
from agentdevstu.work.service import CLOSED, actor, visibility

STOP_WORDS = set(
    (
        "负责 完成 工作 任务 需要 进行 相关 要求 目标 提交 支持 管理 公司 部门 小组 "
        "以及 一个 这个 我们 你们 的 和 与 或 在 是 将 把 为 请 对 了"
    ).split()
)


def keywords(text):
    return {
        w for w in jieba.cut(text.casefold()) if len(w.strip()) >= 2 and re.search(r"[\w]", w) and w not in STOP_WORDS
    }


def score_member(person, task, completed=(), load=0):
    text = " ".join(task.get(k, "") for k in ("title", "goal", "description", "deliverable_requirement")).casefold()
    terms = keywords(text)
    tags = [tag for tag in person["responsibility_tags"] if tag.casefold() in text]
    duties = sorted(
        terms & keywords(" ".join(person[k] for k in ("responsibility", "position_title", "coverage_scope")))
    )
    org = sorted(terms & keywords(person["org_unit_name"]))
    if not (tags or duties or org):
        return None
    history = sum(bool(terms & keywords(previous)) for previous in completed)
    components = {
        "tags": 40 * min(len(tags) / 2, 1),
        "responsibility": 25 * min(len(duties) / 3, 1),
        "organization": 15 if org else 0,
        "history": 10 * min(history / 3, 1),
        "capacity": 10 / (1 + load),
    }
    matches = list(dict.fromkeys(tags + duties + org))
    reason = "匹配：" + "、".join(matches[:8])
    reason += f"；当前可见同类已完成工作 {history} 项，未完成工作 {load} 项"
    return {k: person[k] for k in ("user_id", "display_name", "org_unit_name", "position_title")} | {
        "matched_responsibilities": matches,
        "score": round(sum(components.values()), 2),
        "reason": reason,
        "score_components": {k: round(v, 2) for k, v in components.items()},
    }


async def directory(db):
    ws = actor().workspace_id
    rows = (
        await db.execute(
            select(User, MemberProfile, OrgUnit)
            .join(Membership, and_(Membership.user_id == User.id, Membership.workspace_id == ws))
            .outerjoin(MemberProfile, and_(MemberProfile.user_id == User.id, MemberProfile.workspace_id == ws))
            .outerjoin(OrgUnit, and_(OrgUnit.id == MemberProfile.org_unit_id, OrgUnit.workspace_id == ws))
            .where(User.status == "active")
            .order_by(User.display_name, User.id)
        )
    ).all()
    return [
        {
            "user_id": str(u.id),
            "display_name": u.display_name,
            "org_unit_id": str(p.org_unit_id) if p and p.org_unit_id else None,
            "org_unit_name": o.name if o else "",
            "org_unit_status": o.status if o else None,
            "position_title": p.position_title if p else "",
            "responsibility": p.responsibility if p else "",
            "responsibility_tags": p.responsibility_tags if p else [],
            "coverage_scope": p.coverage_scope if p else "",
            "is_primary": True,
        }
        for u, p, o in rows
    ]


async def recommend(db, task):
    a = actor()
    if not any(task.get(k, "").strip() for k in ("title", "goal", "description", "deliverable_requirement")):
        return []
    people = await directory(db)
    # Preserve Work row visibility; never use hidden work to infer someone's activity.
    works = (
        await db.execute(
            select(Work.assignee_id, Work.status, Work.title, Work.goal).where(
                visibility(a), Work.assignee_type == "human"
            )
        )
    ).all()
    loads = Counter(str(w.assignee_id) for w in works if w.status not in CLOSED)
    history = {}
    for w in works:
        if w.status == "completed":
            history.setdefault(str(w.assignee_id), []).append(w.title + " " + w.goal)
    results = [
        score_member(p, task, history.get(p["user_id"], []), loads[p["user_id"]])
        for p in people
        if p["org_unit_status"] != "disabled"
    ]
    return sorted((r for r in results if r), key=lambda r: (-r["score"], r["display_name"], r["user_id"]))[:3]


async def organization_context(db, workspace_id):
    """Only approved directory fields; no credentials, contacts, roles or task content."""
    a = actor()
    if workspace_id != a.workspace_id:
        from fastapi import HTTPException

        raise HTTPException(403, "组织上下文不属于当前工作空间")
    people = [p for p in await directory(db) if p["org_unit_status"] != "disabled"]
    units = (
        (
            await db.execute(
                select(OrgUnit)
                .where(OrgUnit.workspace_id == workspace_id, OrgUnit.status == "active")
                .order_by(OrgUnit.sort_order, OrgUnit.name, OrgUnit.id)
            )
        )
        .scalars()
        .all()
    )
    ids = {p["user_id"] for p in people}
    data = {
        "workspace_id": str(workspace_id),
        "current_user_id": str(a.user_id),
        "visibility": "当前空间有效成员的组织职责；不是资源访问授权",
        "units": [],
        "members": [],
        "truncated": False,
    }
    for p in sorted(people, key=lambda p: p["user_id"] != str(a.user_id)):
        item = {k: p[k] for k in ("user_id", "display_name", "org_unit_name", "position_title", "responsibility_tags")}
        item.update(responsibility=p["responsibility"][:240], coverage_scope=p["coverage_scope"][:120])
        if len(json.dumps(data, ensure_ascii=False)) + len(json.dumps(item, ensure_ascii=False)) > 7800:
            data["truncated"] = True
            break
        data["members"].append(item)
    for o in units:
        item = {
            "id": str(o.id),
            "parent_id": str(o.parent_id) if o.parent_id else None,
            "name": o.name,
            "manager_user_id": str(o.manager_user_id) if str(o.manager_user_id) in ids else None,
        }
        if len(json.dumps(data, ensure_ascii=False)) + len(json.dumps(item, ensure_ascii=False)) > 10800:
            data["truncated"] = True
            break
        data["units"].append(item)
    return data
