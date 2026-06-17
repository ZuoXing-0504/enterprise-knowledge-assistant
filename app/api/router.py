from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge_bases import router as knowledge_bases_router
from app.api.routes.usage import router as usage_router
from app.api.routes.users import router as users_router
from app.core.config import get_settings

api_router = APIRouter()
api_router.include_router(health_router)

v1_router = APIRouter(prefix=get_settings().api_v1_prefix)
v1_router.include_router(auth_router)
v1_router.include_router(users_router)
v1_router.include_router(knowledge_bases_router)
v1_router.include_router(documents_router)
v1_router.include_router(chat_router)
v1_router.include_router(usage_router)
api_router.include_router(v1_router)
