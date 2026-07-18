from fastapi import APIRouter

from curx.api.demo import router as demo_router
from curx.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(demo_router)
