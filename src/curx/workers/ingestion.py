from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from curx.core.config import Settings
from curx.core.database import create_db_engine, create_session_factory
from curx.domain.ingestion_schemas import IngestionStatus, SourceType
from curx.domain.models import (
    Chunk,
    ChunkEmbedding,
    Document,
    EmbeddingProfile,
    IngestionJob,
    KnowledgeSpace,
    Source,
    utc_now,
)
from curx.services.chunking import HierarchicalChunker
from curx.services.content_loaders import ContentLoadError, load_content, normalize_markdown
from curx.services.embeddings import EmbeddingModel, create_embedding_model
from curx.services.ingestion_service import transition_job
from curx.services.object_store import ObjectStore, create_object_store


def _load_job(db: Session, job_id: UUID) -> IngestionJob | None:
    return db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())


def _cancel_if_requested(db: Session, job: IngestionJob) -> bool:
    db.refresh(job)
    if not job.cancel_requested:
        return False
    current = IngestionStatus(job.status)
    if current in {
        IngestionStatus.QUEUED,
        IngestionStatus.EXTRACTING,
        IngestionStatus.NORMALIZING,
        IngestionStatus.CHUNKING,
        IngestionStatus.EMBEDDING,
    }:
        transition_job(
            db,
            job,
            IngestionStatus.CANCELLED,
            progress_percent=job.progress_percent,
            summary="入库任务已取消。",
        )
        document = db.get(Document, job.document_id)
        if document is not None:
            document.status = IngestionStatus.CANCELLED.value
            db.commit()
    return True


def _embedding_profile(
    db: Session,
    *,
    tenant_id: UUID,
    embedding_model: EmbeddingModel,
) -> EmbeddingProfile:
    fingerprint_payload = {
        "provider": embedding_model.provider,
        "model_name": embedding_model.model_name,
        "dimension": embedding_model.dimension,
        "distance_metric": "cosine",
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    profile = db.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.tenant_id == tenant_id,
            EmbeddingProfile.fingerprint == fingerprint,
        )
    )
    if profile is not None:
        return profile
    profile = EmbeddingProfile(
        tenant_id=tenant_id,
        provider=embedding_model.provider,
        model_name=embedding_model.model_name,
        dimension=embedding_model.dimension,
        distance_metric="cosine",
        fingerprint=fingerprint,
        configuration={"normalization": "l2"},
        enabled=True,
    )
    db.add(profile)
    db.flush()
    return profile


def _finalize_index(
    db: Session,
    *,
    source: Source,
    document: Document,
    job: IngestionJob,
) -> None:
    now = utc_now()
    previous_documents = list(
        db.scalars(
            select(Document).where(
                Document.source_id == source.id,
                Document.id != document.id,
                Document.is_active.is_(True),
            )
        )
    )
    previous_ids = [previous.id for previous in previous_documents]
    for previous in previous_documents:
        previous.is_active = False
        previous.status = IngestionStatus.SUPERSEDED.value
        previous.superseded_at = now
    if previous_ids:
        db.execute(
            update(Chunk)
            .where(Chunk.document_id.in_(previous_ids))
            .values(is_active=False)
        )

    db.execute(
        update(Chunk).where(Chunk.document_id == document.id).values(is_active=True)
    )
    document.status = IngestionStatus.INDEXED.value
    document.is_active = True
    document.indexed_at = now
    document.superseded_at = None
    source.current_version = document.version_number
    source.status = "active"
    db.flush()

    space = db.get(KnowledgeSpace, source.knowledge_space_id)
    if space is not None:
        active_documents = int(
            db.scalar(
                select(func.count(Document.id))
                .join(Source, Source.id == Document.source_id)
                .where(
                    Source.knowledge_space_id == source.knowledge_space_id,
                    Source.status == "active",
                    Document.is_active.is_(True),
                )
            )
            or 0
        )
        active_sources = int(
            db.scalar(
                select(func.count(Source.id)).where(
                    Source.knowledge_space_id == source.knowledge_space_id,
                    Source.status == "active",
                )
            )
            or 0
        )
        space.document_count = active_documents
        space.health_percent = (
            round(active_documents / active_sources * 100) if active_sources else 0
        )
    db.flush()
    transition_job(
        db,
        job,
        IngestionStatus.INDEXED,
        progress_percent=100,
        summary="文档已完成全文与向量索引。",
        event_metadata={
            "document_version": document.version_number,
            "superseded_versions": [item.version_number for item in previous_documents],
        },
    )


def _fail_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    code: str,
    message: str,
) -> None:
    with session_factory() as db:
        job = _load_job(db, job_id)
        if job is None:
            return
        current = IngestionStatus(job.status)
        if current not in {
            IngestionStatus.QUEUED,
            IngestionStatus.EXTRACTING,
            IngestionStatus.NORMALIZING,
            IngestionStatus.CHUNKING,
            IngestionStatus.EMBEDDING,
        }:
            return
        transition_job(
            db,
            job,
            IngestionStatus.FAILED,
            progress_percent=job.progress_percent,
            summary="入库任务失败。",
            error_code=code,
            error_message=message,
        )
        document = db.get(Document, job.document_id)
        if document is not None:
            document.status = IngestionStatus.FAILED.value
            db.commit()


def run_ingestion_job(
    job_id: UUID,
    *,
    session_factory: sessionmaker[Session],
    object_store: ObjectStore,
    embedding_model: EmbeddingModel,
    settings: Settings,
) -> None:
    try:
        with session_factory() as db:
            job = _load_job(db, job_id)
            if job is None or job.status != IngestionStatus.QUEUED.value:
                return
            if _cancel_if_requested(db, job):
                return
            transition_job(
                db,
                job,
                IngestionStatus.EXTRACTING,
                progress_percent=10,
                summary="正在读取原始文件。",
            )
            document = db.get(Document, job.document_id)
            source = db.get(Source, job.source_id)
            if document is None or source is None:
                raise ContentLoadError(
                    "source_state_invalid",
                    "The source or document record is missing.",
                )

            try:
                raw_content = object_store.get_bytes(document.raw_object_key)
            except FileNotFoundError as exc:
                raise ContentLoadError(
                    "raw_object_missing",
                    "The original source file is missing.",
                ) from exc
            extracted = load_content(SourceType(source.source_type), raw_content)
            if _cancel_if_requested(db, job):
                return

            transition_job(
                db,
                job,
                IngestionStatus.NORMALIZING,
                progress_percent=30,
                summary="正在标准化文档结构。",
            )
            normalized_markdown = normalize_markdown(extracted.markdown)
            document.normalized_markdown = normalized_markdown
            document.language = extracted.language
            document.attributes = {
                **document.attributes,
                **extracted.metadata,
            }
            document.status = IngestionStatus.NORMALIZING.value
            db.commit()
            if _cancel_if_requested(db, job):
                return

            transition_job(
                db,
                job,
                IngestionStatus.CHUNKING,
                progress_percent=50,
                summary="正在按标题层级生成稳定分块。",
            )
            chunker = HierarchicalChunker(
                max_tokens=settings.chunk_max_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
            )
            drafts = chunker.chunk(normalized_markdown)
            db.execute(delete(Chunk).where(Chunk.document_id == document.id))
            chunks = [
                Chunk(
                    tenant_id=source.tenant_id,
                    knowledge_space_id=source.knowledge_space_id,
                    source_id=source.id,
                    document_id=document.id,
                    ordinal=draft.ordinal,
                    content=draft.content,
                    token_count=draft.token_count,
                    content_hash=draft.content_hash,
                    heading_path=draft.heading_path,
                    page_number=draft.page_number,
                    location=draft.location,
                    visibility=source.visibility,
                    tags=source.tags,
                    attributes=draft.metadata,
                    is_active=False,
                )
                for draft in drafts
            ]
            db.add_all(chunks)
            document.status = IngestionStatus.CHUNKING.value
            db.commit()
            if _cancel_if_requested(db, job):
                return

            transition_job(
                db,
                job,
                IngestionStatus.EMBEDDING,
                progress_percent=70,
                summary="正在批量生成向量并写入索引。",
                event_metadata={"chunk_count": len(chunks)},
            )
            profile = _embedding_profile(
                db,
                tenant_id=source.tenant_id,
                embedding_model=embedding_model,
            )
            db.execute(
                delete(ChunkEmbedding).where(
                    ChunkEmbedding.chunk_id.in_([chunk.id for chunk in chunks])
                )
            )
            for start in range(0, len(chunks), settings.embedding_batch_size):
                batch = chunks[start : start + settings.embedding_batch_size]
                vectors = embedding_model.embed_documents([chunk.content for chunk in batch])
                if len(vectors) != len(batch):
                    raise ValueError("The embedding provider returned an invalid batch size.")
                db.add_all(
                    [
                        ChunkEmbedding(
                            tenant_id=source.tenant_id,
                            chunk_id=chunk.id,
                            embedding_profile_id=profile.id,
                            embedding=vector,
                        )
                        for chunk, vector in zip(batch, vectors, strict=True)
                    ]
                )
            document.status = IngestionStatus.EMBEDDING.value
            db.commit()
            if _cancel_if_requested(db, job):
                return
            _finalize_index(db, source=source, document=document, job=job)
    except ContentLoadError as exc:
        _fail_job(session_factory, job_id, code=exc.code, message=exc.message)
    except Exception:
        _fail_job(
            session_factory,
            job_id,
            code="ingestion_internal_error",
            message="The ingestion worker failed unexpectedly.",
        )
        raise


async def startup(ctx: dict[str, Any]) -> None:
    settings = Settings()
    engine = create_db_engine(settings)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["object_store"] = create_object_store(settings)
    ctx["embedding_model"] = create_embedding_model(settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["engine"].dispose()


async def process_ingestion_job(ctx: dict[str, Any], job_id: str) -> None:
    await asyncio.to_thread(
        run_ingestion_job,
        UUID(job_id),
        session_factory=ctx["session_factory"],
        object_store=ctx["object_store"],
        embedding_model=ctx["embedding_model"],
        settings=ctx["settings"],
    )


class WorkerSettings:
    functions: list[Callable[..., Any]] = [process_ingestion_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
    max_jobs = 4
    job_timeout = 15 * 60
    max_tries = 1
