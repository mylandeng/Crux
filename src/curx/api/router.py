from fastapi import APIRouter

from curx.api.admin import router as admin_router
from curx.api.auth import router as auth_router
from curx.api.chat import router as chat_router
from curx.api.demo import router as demo_router
from curx.api.health import router as health_router
from curx.api.ingestion import router as ingestion_router
from curx.api.workspace import router as workspace_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(workspace_router)
api_router.include_router(ingestion_router)
api_router.include_router(admin_router)
api_router.include_router(demo_router)
api_router.include_router(chat_router)
