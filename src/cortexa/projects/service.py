"""Project visibility never grants visibility of its works or private conversations."""
import uuid
from datetime import datetime, UTC
from fastapi import HTTPException
from sqlalchemy import and_, delete, or_, select, func
from cortexa.work import service as work
from cortexa.work.models import Work, WorkDeliverable
from .models import Project, ProjectActivity, ProjectAgentGrant, ProjectMember

# 项目-Agent 授权级别：manage 蕴含 use
LEVELS = {'use': 1, 'manage': 2}
LEVEL_LABELS = {'use': '使用', 'manage': '管理'}


def visibility(a):
    scope = Project.workspace_id == a.workspace_id
    if a.has('workspace.manage'):
        return scope
    return and_(scope, or_(Project.creator_id == a.user_id, Project.owner_id == a.user_id,
        Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.workspace_id == a.workspace_id, ProjectMember.user_id == a.user_id))))


def can_manage(p):
    a = work.actor()
    return p.owner_id == a.user_id or p.creator_id == a.user_id or a.has('workspace.manage')


async def get(db, ident, *, manage=False, active=False, lock=False):
    q = select(Project).where(Project.id == ident, visibility(work.actor()))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    p = await db.scalar(q)
    if p is None:
        raise HTTPException(404, '项目不存在或无权访问')
    if manage and not can_manage(p):
        raise HTTPException(403, '仅项目负责人、创建人或空间管理员可修改')
    if active and p.status == 'archived':
        raise HTTPException(409, '归档项目不能新增或移入工作')
    return p


async def activity(db, p, action, data=None):
    p.updated_at = datetime.now(UTC)
    db.add(ProjectActivity(workspace_id=p.workspace_id, project_id=p.id,
        actor_id=work.actor().user_id, action=action, data_json=data or {}))


def grant_allows(level, need):
    """manage 蕴含 use；无授权（None）不满足任何级别。"""
    return LEVELS.get(level or '', 0) >= LEVELS.get(need, 0)


async def agent_grant_level(db, project_id, agent_id) -> str | None:
    return await db.scalar(select(ProjectAgentGrant.level).where(
        ProjectAgentGrant.project_id == project_id, ProjectAgentGrant.agent_id == agent_id))


async def require_agent_grant(db, project_id, agent_id, need='use'):
    level = await agent_grant_level(db, project_id, agent_id)
    if not grant_allows(level, need):
        raise HTTPException(403, f"本 Agent 未获得该项目的{LEVEL_LABELS[need]}授权，请在项目「Agent 授权」中添加后重试")
    return level


async def agent_grants(db, project_id):
    from cortexa.db.models import Agent
    rows = (await db.execute(
        select(ProjectAgentGrant, Agent.name, Agent.avatar)
        .join(Agent, Agent.id == ProjectAgentGrant.agent_id)
        .where(ProjectAgentGrant.project_id == project_id)
        .order_by(ProjectAgentGrant.created_at))).all()
    return [{'agent_id': g.agent_id, 'agent_name': name or '', 'agent_avatar': avatar, 'level': g.level}
            for g, name, avatar in rows]


async def replace_agent_grants(db, project, items):
    """整体替换项目的 Agent 授权（仿 member_ids 模式）；返回授权列表。"""
    deduped = {}
    for item in items:
        aid, level = item.get('agent_id'), item.get('level', 'use')
        if level not in LEVELS:
            raise HTTPException(422, f"无效的权限级别：{level}（仅支持 manage/use）")
        deduped[aid] = level  # 同一 Agent 后写的级别生效
    cleaned = list(deduped.items())
    from cortexa.db.models import Agent
    if cleaned:
        known = set(await db.scalars(select(Agent.id).where(
            Agent.id.in_([aid for aid, _ in cleaned]), Agent.workspace_id == project.workspace_id)))
        missing = [str(aid) for aid, _ in cleaned if aid not in known]
        if missing:
            raise HTTPException(422, "以下 Agent 不属于当前工作空间：" + "、".join(missing))
    await db.execute(delete(ProjectAgentGrant).where(ProjectAgentGrant.project_id == project.id))
    for aid, level in cleaned:
        db.add(ProjectAgentGrant(workspace_id=project.workspace_id, project_id=project.id, agent_id=aid, level=level))
    await activity(db, project, 'agent_grants_changed', {'agents': [{'agent_id': str(a), 'level': l} for a, l in cleaned]})
    return cleaned


async def output(db, p):
    counts = dict((await db.execute(select(Work.status, func.count()).where(
        Work.project_id == p.id, work.visibility(work.actor())).group_by(Work.status))).all())
    total = sum(counts.values())
    from cortexa.security.models import User
    owner = await db.get(User, p.owner_id) if p.owner_id else None
    return {**work.serialize(p), 'owner_name': owner.display_name if owner else '',
        'permissions': {'manage':can_manage(p)}, 'counts':counts, 'visible_work_count':total,
        'progress':round(100 * counts.get('completed',0) / total) if total else 0,
        'statistics_scope':'按可见工作统计'}


async def summaries(db, ids, *, budget=6000, agent_id=None):
    import json
    result, refs = [], []
    for ident in dict.fromkeys(str(i) for i in ids):
        p = await get(db, uuid.UUID(ident))
        if agent_id is not None and not grant_allows(await agent_grant_level(db, p.id, agent_id), 'use'):
            # 严格授权：未获得使用授权的项目不注入任何内容，只留一行说明供 Agent 向用户转达。
            notice = json.dumps({'project_id': ident,
                'notice': '本 Agent 未获得该项目的使用授权，项目内容未注入；请提示用户在项目「Agent 授权」中添加'}, ensure_ascii=False)
            budget -= len(notice.encode())
            if budget < 0:
                raise HTTPException(422, '项目引用超出本轮上下文预算，请减少引用')
            result.append(notice)
            continue
        rows = (await db.scalars(select(Work).where(Work.project_id == p.id,
            work.visibility(work.actor())).order_by(Work.updated_at.desc()).limit(20))).all()
        from cortexa.security.models import User
        people = {u.id:u.display_name for u in await db.scalars(select(User).where(User.id.in_({p.owner_id,*[w.assignee_id for w in rows if w.assignee_type == 'human']})))}
        deliveries = (await db.execute(select(WorkDeliverable, Work.title).join(Work,Work.id == WorkDeliverable.work_id).where(Work.project_id == p.id, Work.status == 'completed',work.visibility(work.actor())).order_by(WorkDeliverable.created_at.desc()).limit(10))).all()
        summary = {'project_id':ident, 'title':p.title, 'goal':p.goal, 'scope':p.scope,
            'status':p.status, 'owner':people.get(p.owner_id,'未设置'), 'accepted_deliverables':[{'work_title':title,'summary_excerpt':d.content[:300],'type':d.type} for d,title in deliveries],
            'due_at':p.due_at.isoformat() if p.due_at else None,
            'statistics_scope':'仅包含当前用户可见工作；最多列出20项，其他内容按需读取',
            'works':[{'id':str(w.id),'title':w.title,'status':w.status,'goal':w.goal,'assignee':people.get(w.assignee_id,'Agent') if w.assignee_type == 'human' else 'Agent',
                      'overdue': bool(w.due_at and w.due_at < datetime.now(UTC) and w.status not in {'completed','cancelled'}), 'due_at':w.due_at.isoformat() if w.due_at else None} for w in rows]}
        text = json.dumps(summary,ensure_ascii=False)
        if len(text.encode()) > budget:
            summary['works'] = []
            summary['accepted_deliverables'] = []
            summary['scope'] = p.scope[:500]
            summary['goal'] = p.goal[:500]
            summary['notice'] = '上下文预算限制：工作详情需按需读取'
            text = json.dumps(summary,ensure_ascii=False)
        if len(text.encode()) > budget:
            raise HTTPException(422, '项目引用超出本轮上下文预算，请减少引用')
        budget -= len(text.encode())
        result.append(text)
        refs.append({'type':'project','project_id':ident,'name':p.title})
    return '\n\n'.join(result), refs


async def read_detail(db, project_id, work_id=None):
    p = await get(db, project_id)
    if work_id:
        w = await work.get_work(db, work_id)
        if w.project_id != p.id:
            raise HTTPException(404, '工作不属于所引用项目')
        deliveries = (await db.scalars(select(WorkDeliverable).where(WorkDeliverable.work_id == w.id).limit(20))).all()
        return {'project_id':str(p.id),'work':await work.output(db,w),
            'deliverables':[{'id':str(d.id),'type':d.type,'summary':d.content,'filename':d.filename,
                             'accepted':w.status == 'completed'} for d in deliveries]}
    rows = (await db.scalars(select(Work).where(Work.project_id == p.id,work.visibility(work.actor()))
        .order_by(Work.updated_at.desc()).limit(50))).all()
    return {'project':await output(db,p),'works':[{'id':str(w.id),'title':w.title,'status':w.status} for w in rows],
            'notice':'仅显示当前用户可见工作，最多50项'}
