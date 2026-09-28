"""API Router."""

from fastapi import APIRouter

from cortexa.api.agents import router as agents_router
from cortexa.api.workspaces import router as workspaces_router
from cortexa.api.conversations import router as conversations_router
from cortexa.api.knowledge import router as knowledge_router
from cortexa.api.tools import router as tools_router
from cortexa.api.workflows import router as workflows_router
from cortexa.api.tasks import router as tasks_router
from cortexa.api.meetings import router as meetings_router
from cortexa.api.data import router as data_router
from cortexa.api.collaboration import router as collaboration_router
from cortexa.api.memories import router as memories_router
from cortexa.api.agent_operations import router as agent_operations_router

api_router = APIRouter(prefix="/api")

api_router.include_router(agents_router)
api_router.include_router(workspaces_router)
api_router.include_router(conversations_router)
from cortexa.api.goals import router as goals_router
api_router.include_router(goals_router)
from cortexa.api.runtime_policy import router as runtime_policy_router
api_router.include_router(runtime_policy_router)
api_router.include_router(knowledge_router)
api_router.include_router(tools_router)
api_router.include_router(workflows_router)
api_router.include_router(tasks_router)
api_router.include_router(meetings_router)
api_router.include_router(data_router)
api_router.include_router(collaboration_router)
api_router.include_router(memories_router)
api_router.include_router(agent_operations_router)

from cortexa.security.api import router as identity_router
api_router.include_router(identity_router)

from cortexa.api.works import router as works_router
api_router.include_router(works_router)

from cortexa.api.organization import router as organization_router
api_router.include_router(organization_router)

from cortexa.api.schema_generation import router as schema_generation_router
api_router.include_router(schema_generation_router)

from cortexa.api.sql_drafts import router as sql_drafts_router
api_router.include_router(sql_drafts_router, prefix="/data")

from cortexa.usage.api import router as usage_router
api_router.include_router(usage_router)
