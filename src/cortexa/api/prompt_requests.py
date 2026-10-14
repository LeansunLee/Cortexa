"""Authorized, on-demand access to captured model/collaboration requests."""
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from cortexa.db.engine import async_session_factory
from cortexa.runtime.prompt_requests import read_prompt
from cortexa.runtime.shadow import can_read_goal_trace
from cortexa.runtime.store import own_conversation
from cortexa.security.access import require_agent_use

router = APIRouter(prefix='/conversations', tags=['prompt requests'])


@router.get('/{conv_id}/prompts/{prompt_id}')
async def get_prompt(conv_id: uuid.UUID, prompt_id: uuid.UUID):
    async with async_session_factory() as db:
        await own_conversation(db, conv_id, use_agent=True)
        if not can_read_goal_trace():
            raise HTTPException(403, '需要开启对话调试并拥有调试权限')
        try:
            snapshot = read_prompt(prompt_id)
        except (OSError, ValueError):
            raise HTTPException(404, '提示词记录不存在') from None
        if snapshot.get('conversation_id') != str(conv_id):
            raise HTTPException(404, '提示词记录不存在')
        await require_agent_use(db, uuid.UUID(snapshot['agent_id']))
    return JSONResponse(snapshot, headers={'Cache-Control': 'no-store'})
