import asyncio
import os
import uuid
from dataclasses import replace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from cortexa.projects import service as s
from cortexa.projects.models import Project, ProjectMember, ProjectActivity
from cortexa.api import projects as api
from cortexa.work.models import Work, WorkDeliverable
from cortexa.work.schemas import WorkInput
from cortexa.work import service as work
from cortexa.security.models import User, Membership
from cortexa.security.access import Actor, current_actor
from test_goal_collaboration import setup

URL=os.getenv('GOAL_TEST_DATABASE_URL')


@pytest.mark.skipif(not URL,reason='Isolated PostgreSQL required')
def test_projects_visibility_membership_assignment_budget_and_archive(tmp_path,monkeypatch):
    async def scenario():
        async with setup(tmp_path,monkeypatch) as ctx:
            a=ctx.actor
            other=uuid.uuid4()
            async with ctx.store.sessions() as db:
                db.add(User(id=other,username='member-'+str(other),display_name='成员',password_hash='test'))
                await db.flush()
                db.add_all([Membership(user_id=other,workspace_id=a.workspace_id),Membership(user_id=a.user_id,workspace_id=a.workspace_id)])
                await db.commit()
            async with ctx.store.sessions() as db:
                p=await api.save(db,api.ProjectInput(title='浙江拓展',goal='拓展新门店',owner_id=a.user_id,member_ids=[other]))
                await db.commit();pid=p.id
                w=await work.create(db,WorkInput(title='目标测算',goal='测算浙江销售目标',assignee_id=other,reviewer_id=a.user_id,project_id=pid))
                await db.commit();wid=w.id
                # Associate existing in-progress work without resetting its state.
                w.status='in_progress';await db.commit()
                await api.assign(wid,api.Assignment(project_id=None),db)
                assert w.status=='in_progress'
                await api.assign(wid,api.Assignment(project_id=pid),db)
                assert w.status=='in_progress'
                text,refs=await s.summaries(db,[pid],budget=3000)
                assert '目标测算' in text and refs[0]['project_id']==str(pid)
                with pytest.raises(HTTPException):await s.summaries(db,[pid],budget=40)
                db.add(WorkDeliverable(workspace_id=a.workspace_id,work_id=wid,type='text',content='数据成果',submitted_by=a.user_id,metadata_json={}))
                await db.commit()
                assert (await api.deliverables(pid,0,50,db))[0]['accepted'] is False
                assert (await s.read_detail(db,pid,wid))['deliverables'][0]['summary']=='数据成果'
                # Create a work hidden from member even though the project is visible.
                hidden=Work(workspace_id=a.workspace_id,project_id=pid,title='隐私工作',goal='PRIVATE_GOAL',assignee_type='human',assignee_id=a.user_id,creator_id=a.user_id,reviewer_id=a.user_id,status='todo',priority='P2',source_type='manual')
                db.add(hidden);await db.flush()
                await s.activity(db,p,'work_changed',{'work_id':str(hidden.id),'title':'隐私工作'})
                await db.commit()
            member_actor=Actor(user_id=other,username='member',superadmin=False,must_change=False,version=1,workspace_id=a.workspace_id,memberships={a.workspace_id:{'permissions':{'agent.use'},'all_agents':False,'agent_ids':{ctx.source.id}}})
            token=current_actor.set(member_actor)
            try:
                async with ctx.store.sessions() as db:
                    p=await s.get(db,pid)
                    out=await s.output(db,p)
                    assert out['visible_work_count']==1
                    text,_=await s.summaries(db,[pid])
                    assert '隐私工作' not in text and 'PRIVATE_GOAL' not in text
                    assert '隐私工作' not in str(await api.activities(pid,db))
                    with pytest.raises(HTTPException):await s.get(db,pid,manage=True)
                    with pytest.raises(HTTPException):await s.read_detail(db,pid,hidden.id)
                    with pytest.raises(HTTPException):await api.assign(wid,api.Assignment(project_id=None),db)
            finally:current_actor.reset(token)
            async with ctx.store.sessions() as db:
                await api.archive(pid,db);await db.commit()
                with pytest.raises(HTTPException):await work.create(db,WorkInput(title='不能移入',goal='归档项目新增工作',assignee_id=other,project_id=pid))
                # Removing archived association is allowed; no work state reset.
                out=await api.assign(wid,api.Assignment(project_id=None),db)
                assert out['project_id'] is None and out['status']=='in_progress'
                assert any(a['data_json'].get('work_id') == str(wid) for a in await api.activities(pid,db))
                await db.commit()
                assert await db.scalar(select(ProjectActivity.id).where(ProjectActivity.project_id==pid))
    asyncio.run(scenario())


@pytest.mark.skipif(not URL,reason='Isolated PostgreSQL required')
def test_project_read_only_tool_and_goal_reference(tmp_path,monkeypatch):
    from cortexa.projects import runtime
    from cortexa.api import goals
    from test_goal_loop import FakeModel
    from langchain_core.messages import AIMessageChunk
    async def scenario():
        async with setup(tmp_path,monkeypatch) as ctx:
            async with ctx.store.sessions() as db:
                db.add(Membership(user_id=ctx.actor.user_id,workspace_id=ctx.actor.workspace_id));await db.commit()
                p=await api.save(db,api.ProjectInput(title='项目引用测试',goal='REFERENCE_GOAL',owner_id=ctx.actor.user_id))
                await db.commit();pid=p.id
            monkeypatch.setattr(runtime,'async_session_factory',ctx.store.sessions)
            refs=[];tool=runtime.tools(ctx.source.id,[pid],refs)[0]
            result=await tool.ainvoke({'project_id':str(pid)})
            assert result['success'] and result['result']['project']['goal']=='REFERENCE_GOAL'
            assert refs[0]['type']=='project'
            assert (await tool.ainvoke({'project_id':str(uuid.uuid4())}))['success'] is False
            model=FakeModel([[AIMessageChunk(content='项目摘要已读取。')]])
            monkeypatch.setattr(goals,'create_llm',lambda *_:model)
            response=await goals.create_goal_stream(ctx.conv,goals.GoalRequest(content='总结项目',idempotency_key='project-ref',project_ids=[pid]))
            events=[]
            async for chunk in response.body_iterator:
                for line in (chunk.decode() if isinstance(chunk,bytes) else chunk).splitlines():
                    if line.startswith('data: '):
                        import json
                        events.append(json.loads(line[6:]))
            done=next(e for e in reversed(events) if e['type']=='done')
            assert done['project_ids']==[str(pid)]
            assert any(s.get('project_id')==str(pid) for s in done['sources'])
            row=await ctx.store.get(ctx.conv,uuid.UUID(done['goal_id']))
            payload=ctx.store.files.read(row.id,row.artifacts['snapshot'])
            assert 'REFERENCE_GOAL' in str(payload['messages'])
    asyncio.run(scenario())


@pytest.mark.skipif(not URL,reason='Isolated PostgreSQL required')
def test_additive_migration_preserves_unassigned_works(tmp_path,monkeypatch):
    from pathlib import Path
    from sqlalchemy import text
    async def scenario():
        async with setup(tmp_path,monkeypatch) as ctx:
            wid=uuid.uuid4()
            async with ctx.store.sessions() as db:
                db.add(Work(id=wid,workspace_id=ctx.actor.workspace_id,title='历史工作',goal='历史目标',
                            assignee_type='human',assignee_id=ctx.actor.user_id,creator_id=ctx.actor.user_id,
                            reviewer_id=ctx.actor.user_id,status='todo',priority='P2',source_type='manual'))
                await db.commit()
                await db.execute(text('ALTER TABLE t_works DROP COLUMN project_id CASCADE'))
                await db.execute(text('DROP TABLE t_project_activities, t_project_members, t_projects'))
                await db.commit()
                conn=await db.connection();raw=await conn.get_raw_connection()
                await raw.driver_connection.execute(Path('migrations/add_projects_20261013.sql').read_text())
                row=await db.scalar(select(Work).where(Work.id==wid))
                assert row.title=='历史工作' and row.project_id is None
    asyncio.run(scenario())
