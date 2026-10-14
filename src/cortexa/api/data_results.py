"""On-demand inspection of archived query results, without executing queries."""
import json
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select

from cortexa.db.engine import async_session_factory
from cortexa.db.models import AgentDataBinding, DataCapability
from cortexa.runtime.artifacts import ArtifactStore
from cortexa.runtime.models import RuntimeGoal
from cortexa.runtime.store import own_conversation, owned
from cortexa.security.access import require_agent_use

router = APIRouter(prefix='/conversations', tags=['query results'])


def find_result(snapshot, agent_id, action_id):
    for observation in snapshot.get('observations', []):
        if observation.get('action_id') == str(action_id) and observation.get('source_type') == 'DATA':
            return agent_id, observation
    for run in snapshot.get('agent_runs', {}).values():
        child_agent = run.get('state', {}).get('runtime_agent_id')
        if child_agent:
            found = find_result(run.get('payload', {}), child_agent, action_id)
            if found:
                return found
    return None


def result_page(observation, offset, limit):
    raw = observation.get('raw_result')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    # Only query records and safe result metadata, never the entire runtime snapshot.
    rows = raw.get('data') if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        rows = observation.get('facts')
    if not isinstance(rows, list):
        raise HTTPException(404, '该步骤没有可查看的查询记录')
    metadata = observation.get('metadata') or {}
    info = raw if isinstance(raw, dict) else metadata
    columns = list(dict.fromkeys(key for row in rows if isinstance(row, dict) for key in row))
    return {'status': observation.get('status'), 'columns': columns,
            'rows': rows[offset:offset + limit], 'returned_rows': len(rows),
            'row_count': info.get('row_count', metadata.get('row_count')),
            'truncated': bool(info.get('truncated', metadata.get('truncated', False))),
            'offset': offset, 'limit': limit}


@router.get('/{conv_id}/data-results/{action_id}')
async def get_data_result(conv_id: uuid.UUID, action_id: uuid.UUID,
                          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    async with async_session_factory() as db:
        await own_conversation(db, conv_id, use_agent=True)
        rows = await db.scalars(select(RuntimeGoal).where(*owned(), RuntimeGoal.conversation_id == conv_id))
        for row in rows:
            try:
                snapshot = ArtifactStore().read(row.id, row.artifacts['snapshot'])
            except (OSError, ValueError, KeyError):
                continue
            found = find_result(snapshot, str(row.agent_id), action_id)
            if not found:
                continue
            agent_id, observation = found
            agent = await require_agent_use(db, uuid.UUID(agent_id))
            try:
                cap_id = uuid.UUID(observation['source_id'].removeprefix('data:'))
            except (KeyError, ValueError):
                raise HTTPException(404, '查询记录不存在') from None
            granted = await db.scalar(select(DataCapability.id).join(
                AgentDataBinding, AgentDataBinding.data_capability_id == DataCapability.id).where(
                    AgentDataBinding.agent_id == agent.id, DataCapability.id == cap_id,
                    DataCapability.workspace_id == agent.workspace_id, DataCapability.status == 'active'))
            if granted is None:
                raise HTTPException(403, '该数据能力的访问权限已撤销')
            return JSONResponse(result_page(observation, offset, limit), headers={'Cache-Control': 'no-store'})
    raise HTTPException(404, '查询记录未保存或不可访问')
