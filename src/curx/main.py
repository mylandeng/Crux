from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from curx.api.router import api_router
from curx.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Evidence-backed internal knowledge Q&A platform.",
    )
    app.include_router(api_router, prefix=settings.api_prefix)

    web_dir = Path(__file__).parent / "web"
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
