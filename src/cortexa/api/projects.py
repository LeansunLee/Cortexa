import uuid
from typing import Literal
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from cortexa.db.engine import get_db_session
from cortexa.projects.models import Project, ProjectMember, ProjectActivity
from cortexa.projects import service as s
from cortexa.work import service as work
from cortexa.work.models import Work, WorkDeliverable

router = APIRouter(prefix='/projects', tags=['projects'])


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    title: str = Field(min_length=1,max_length=200)
    goal: str = Field(min_length=1,max_length=2000)
    scope: str = Field(default='',max_length=4000)
    owner_id: uuid.UUID
    status: Literal['planned','active','completed','archived'] = 'planned'
    due_at: datetime | None = None
    member_ids: list[uuid.UUID] = Field(default_factory=list,max_length=100)
    @field_validator('due_at')
    @classmethod
    def timezone(cls,value):
        if value and not value.tzinfo:
            raise ValueError('截止时间必须包含时区')
        return value


async def save(db, data, p=None):
    a = work.actor()
    for ident in set([data.owner_id,*data.member_ids]):
        await work.member(db,ident)
    if p is None:
        p = Project(**data.model_dump(exclude={'member_ids'}),workspace_id=a.workspace_id,creator_id=a.user_id)
        db.add(p)
        await db.flush()
        action = 'created'
    else:
        action = 'updated'
        for key,value in data.model_dump(exclude={'member_ids'}).items():
            setattr(p,key,value)
        await db.execute(delete(ProjectMember).where(ProjectMember.project_id == p.id,ProjectMember.workspace_id == a.workspace_id))
    for ident in set(data.member_ids):
        db.add(ProjectMember(workspace_id=a.workspace_id,project_id=p.id,user_id=ident))
    await s.activity(db,p,action,{'status':p.status})
    await db.flush()
    return p


@router.get('')
async def listing(search:str='',status:str='',offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100),db:AsyncSession=Depends(get_db_session)):
    q = select(Project).where(s.visibility(work.actor()))
    if search:q = q.where(Project.title.icontains(search[:200],autoescape=True))
    if status:q = q.where(Project.status == status)
    return [await s.output(db,p) for p in await db.scalars(q.order_by(Project.updated_at.desc(),Project.id).offset(offset).limit(limit))]


@router.post('',status_code=201)
async def create(data:ProjectInput,db:AsyncSession=Depends(get_db_session)):
    return await s.output(db,await save(db,data))


@router.get('/{ident}')
async def detail(ident:uuid.UUID,db:AsyncSession=Depends(get_db_session)):
    p=await s.get(db,ident)
    members=await db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == p.id))
    return {**await s.output(db,p),'member_ids':list(members)}


@router.patch('/{ident}')
async def edit(ident:uuid.UUID,data:ProjectInput,db:AsyncSession=Depends(get_db_session)):
    p=await s.get(db,ident,manage=True,lock=True)
    return await s.output(db,await save(db,data,p))


@router.post('/{ident}/archive')
async def archive(ident:uuid.UUID,db:AsyncSession=Depends(get_db_session)):
    p=await s.get(db,ident,manage=True,lock=True)
    p.status='archived'
    await s.activity(db,p,'archived')
    return await s.output(db,p)


class Assignment(BaseModel):
    project_id:uuid.UUID | None = None


@router.patch('/works/{work_id}/assignment')
async def assign(work_id:uuid.UUID,data:Assignment,db:AsyncSession=Depends(get_db_session)):
    # Separate association permission: attaching never resets work execution state.
    w=await work.get_work(db,work_id,lock=True)
    a=work.actor()
    if not (w.creator_id == a.user_id or a.has('workspace.manage')):
        from fastapi import HTTPException
        raise HTTPException(403,'仅工作创建人或空间管理员可修改项目归属')
    previous=w.project_id
    if data.project_id:await s.get(db,data.project_id,active=True,lock=True)
    if previous:await s.get(db,previous,lock=True)
    w.project_id=data.project_id
    await work.event(db,w,'project_changed',{'before':str(previous) if previous else None,'after':str(data.project_id) if data.project_id else None})
    for ident in {previous,data.project_id}-{None}:
        p=await s.get(db,ident)
        await s.activity(db,p,'work_changed',{'work_id':str(w.id),'title':w.title})
    return await work.output(db,w)


@router.get('/{ident}/deliverables')
async def deliverables(ident:uuid.UUID,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:AsyncSession=Depends(get_db_session)):
    await s.get(db,ident)
    q=select(WorkDeliverable,Work.title,Work.status).join(Work,Work.id == WorkDeliverable.work_id).where(Work.project_id == ident,work.visibility(work.actor())).order_by(WorkDeliverable.created_at.desc()).offset(offset).limit(limit)
    return [{**work.serialize(d),'work_title':title,'accepted':status == 'completed'} for d,title,status in (await db.execute(q)).all()]


@router.get('/{ident}/activities')
async def activities(ident:uuid.UUID,db:AsyncSession=Depends(get_db_session)):
    await s.get(db,ident)
    rows=(await db.scalars(select(ProjectActivity).where(ProjectActivity.project_id == ident).order_by(ProjectActivity.created_at.desc()).limit(100))).all()
    ids={uuid.UUID(row.data_json['work_id']) for row in rows if row.data_json.get('work_id')}
    visible=set(await db.scalars(select(Work.id).where(Work.id.in_(ids),work.visibility(work.actor()))))
    return [work.serialize(row) for row in rows if not row.data_json.get('work_id') or uuid.UUID(row.data_json['work_id']) in visible]
