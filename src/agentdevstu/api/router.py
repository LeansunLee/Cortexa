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
from agentdevstu.api.data import router as data_router
from agentdevstu.api.collaboration import router as collaboration_router
from agentdevstu.api.memories import router as memories_router
from agentdevstu.api.agent_operations import router as agent_operations_router

api_router = APIRouter(prefix="/api")

api_router.include_router(agents_router)
api_router.include_router(workspaces_router)
api_router.include_router(conversations_router)
api_router.include_router(knowledge_router)
api_router.include_router(tools_router)
api_router.include_router(workflows_router)
api_router.include_router(tasks_router)
api_router.include_router(meetings_router)
api_router.include_router(data_router)
api_router.include_router(collaboration_router)
api_router.include_router(memories_router)
api_router.include_router(agent_operations_router)

from agentdevstu.security.api import router as identity_router
api_router.include_router(identity_router)

from agentdevstu.api.works import router as works_router
api_router.include_router(works_router)

from agentdevstu.api.organization import router as organization_router
api_router.include_router(organization_router)

from agentdevstu.api.schema_generation import router as schema_generation_router
api_router.include_router(schema_generation_router)

from agentdevstu.api.sql_drafts import router as sql_drafts_router
api_router.include_router(sql_drafts_router, prefix="/data")

from agentdevstu.usage.api import router as usage_router
api_router.include_router(usage_router)
