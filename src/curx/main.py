from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from curx.api.router import api_router
from curx.core.config import Settings, get_settings
from curx.core.database import create_db_engine, create_session_factory
from curx.services.embeddings import create_embedding_model
from curx.services.job_queue import (
    ArqIngestionJobQueue,
    IngestionJobQueue,
    InlineIngestionJobQueue,
)
from curx.services.object_store import ObjectStore, create_object_store
from curx.workers.ingestion import run_ingestion_job


def create_app(
    settings: Settings | None = None,
    db_session_factory: sessionmaker[Session] | None = None,
    object_store: ObjectStore | None = None,
    ingestion_job_queue: IngestionJobQueue | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    engine = None
    if db_session_factory is None:
        engine = create_db_engine(resolved_settings)
        db_session_factory = create_session_factory(engine)
    object_store = object_store or create_object_store(resolved_settings)
    if ingestion_job_queue is None:
        if resolved_settings.ingestion_inline:
            embedding_model = create_embedding_model(resolved_settings)

            def run_inline(job_id: UUID) -> None:
                run_ingestion_job(
                    job_id,
                    session_factory=db_session_factory,
                    object_store=object_store,
                    embedding_model=embedding_model,
                    settings=resolved_settings,
                )

            ingestion_job_queue = InlineIngestionJobQueue(run_inline)
        else:
            ingestion_job_queue = ArqIngestionJobQueue(resolved_settings.redis_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await ingestion_job_queue.close()
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Evidence-backed internal knowledge Q&A platform.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.db_session_factory = db_session_factory
    app.state.object_store = object_store
    app.state.ingestion_job_queue = ingestion_job_queue

    def app_settings() -> Settings:
        return resolved_settings

    app.dependency_overrides[get_settings] = app_settings
    app.include_router(api_router, prefix=resolved_settings.api_prefix)

    web_dir = Path(__file__).parent / "web"
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
