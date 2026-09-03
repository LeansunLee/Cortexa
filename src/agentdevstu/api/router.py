"""API Router."""

from fastapi import APIRouter

from agentdevstu.api.agents import router as agents_router
from agentdevstu.api.workspaces import router as workspaces_router
from agentdevstu.api.conversations import router as conversations_router
from agentdevstu.api.knowledge import router as knowledge_router
from agentdevstu.api.tools import router as tools_router
from agentdevstu.api.workflows import router as workflows_router
from agentdevstu.api.tasks import router as tasks_router
from agentdevstu.api.meetings import router as meetings_router

api_router = APIRouter(prefix="/api")

api_router.include_router(agents_router)
api_router.include_router(workspaces_router)
api_router.include_router(conversations_router)
api_router.include_router(knowledge_router)
api_router.include_router(tools_router)
api_router.include_router(workflows_router)
api_router.include_router(tasks_router)
api_router.include_router(meetings_router)
