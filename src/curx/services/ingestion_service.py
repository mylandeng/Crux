from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from curx.core.config import Settings
from curx.domain.ingestion_schemas import (
    ACTIVE_INGESTION_STATUSES,
    DocumentVersionResponse,
    IngestionJobEventResponse,
    IngestionJobResponse,
    IngestionStatus,
    SourceDetailResponse,
    SourceSubmissionResponse,
    SourceSummaryResponse,
    SourceType,
)
from curx.domain.models import (
    Chunk,
    Document,
    IngestionJob,
    IngestionJobEvent,
    KnowledgeSpace,
    Source,
    UserKnowledgeSpaceGrant,
    utc_now,
)
from curx.services.identity_service import (
    AuthenticatedIdentity,
    RequestMetadata,
    record_audit,
)
from curx.services.object_store import ObjectStore

ALLOWED_TRANSITIONS: dict[IngestionStatus, set[IngestionStatus]] = {
    IngestionStatus.QUEUED: {
        IngestionStatus.EXTRACTING,
        IngestionStatus.CANCELLED,
        IngestionStatus.FAILED,
    },
    IngestionStatus.EXTRACTING: {
        IngestionStatus.NORMALIZING,
        IngestionStatus.CANCELLED,
        IngestionStatus.FAILED,
    },
    IngestionStatus.NORMALIZING: {
        IngestionStatus.CHUNKING,
        IngestionStatus.CANCELLED,
        IngestionStatus.FAILED,
    },
    IngestionStatus.CHUNKING: {
        IngestionStatus.EMBEDDING,
        IngestionStatus.CANCELLED,
        IngestionStatus.FAILED,
    },
    IngestionStatus.EMBEDDING: {
        IngestionStatus.INDEXED,
        IngestionStatus.CANCELLED,
        IngestionStatus.FAILED,
    },
}


class IngestionError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SourceSubmission:
    source: Source
    job: IngestionJob
    deduplicated: bool


def require_space_access(
    db: Session,
    identity: AuthenticatedIdentity,
    knowledge_space_id: UUID,
    *,
    write: bool = False,
) -> tuple[KnowledgeSpace, UserKnowledgeSpaceGrant]:
    result = db.execute(
        select(KnowledgeSpace, UserKnowledgeSpaceGrant)
        .join(
            UserKnowledgeSpaceGrant,
            UserKnowledgeSpaceGrant.knowledge_space_id == KnowledgeSpace.id,
        )
        .where(
            KnowledgeSpace.id == knowledge_space_id,
            KnowledgeSpace.tenant_id == identity.tenant.id,
            KnowledgeSpace.status == "active",
            UserKnowledgeSpaceGrant.user_id == identity.user.id,
            UserKnowledgeSpaceGrant.can_read.is_(True),
        )
    ).one_or_none()
    if result is None:
        raise IngestionError(404, "knowledge_space_not_found", "Knowledge space not found.")
    space, grant = result
    if write and not grant.can_write:
        raise IngestionError(
            403,
            "knowledge_write_required",
            "Write access to this knowledge space is required.",
        )
    return space, grant


def _latest_job(db: Session, source_id: UUID) -> IngestionJob | None:
    return db.scalar(
        select(IngestionJob)
        .options(selectinload(IngestionJob.events))
        .where(IngestionJob.source_id == source_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )


def _source_for_identity(
    db: Session,
    identity: AuthenticatedIdentity,
    source_id: UUID,
    *,
    write: bool = False,
) -> Source:
    source = db.scalar(
        select(Source).where(
            Source.id == source_id,
            Source.tenant_id == identity.tenant.id,
            Source.status != "deleted",
        )
    )
    if source is None:
        raise IngestionError(404, "source_not_found", "Source not found.")
    require_space_access(db, identity, source.knowledge_space_id, write=write)
    return source


def _job_for_identity(
    db: Session,
    identity: AuthenticatedIdentity,
    job_id: UUID,
    *,
    write: bool = False,
) -> IngestionJob:
    job = db.scalar(
        select(IngestionJob)
        .options(selectinload(IngestionJob.events))
        .where(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == identity.tenant.id,
        )
    )
    if job is None:
        raise IngestionError(404, "ingestion_job_not_found", "Ingestion job not found.")
    require_space_access(db, identity, job.knowledge_space_id, write=write)
    return job


def _new_job(
    *,
    source: Source,
    document: Document,
    requested_by_user_id: UUID,
    settings: Settings,
) -> IngestionJob:
    job = IngestionJob(
        tenant_id=source.tenant_id,
        knowledge_space_id=source.knowledge_space_id,
        source_id=source.id,
        document_id=document.id,
        requested_by_user_id=requested_by_user_id,
        status=IngestionStatus.QUEUED.value,
        progress_percent=0,
        max_attempts=settings.ingestion_max_attempts,
        correlation_id=uuid4().hex,
    )
    job.events.append(
        IngestionJobEvent(
            tenant_id=source.tenant_id,
            status=IngestionStatus.QUEUED.value,
            progress_percent=0,
            attempt_number=0,
            summary="入库任务已排队。",
        )
    )
    return job


def submit_source(
    db: Session,
    *,
    object_store: ObjectStore,
    settings: Settings,
    identity: AuthenticatedIdentity,
    metadata: RequestMetadata,
    knowledge_space_id: UUID,
    source_type: SourceType,
    title: str,
    content: bytes,
    mime_type: str,
    original_filename: str | None = None,
    uri: str | None = None,
    visibility: str = "space",
    tags: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> SourceSubmission:
    require_space_access(db, identity, knowledge_space_id, write=True)
    if not content:
        raise IngestionError(422, "empty_upload", "The source content is empty.")
    if len(content) > settings.ingestion_max_upload_bytes:
        raise IngestionError(413, "upload_too_large", "The source exceeds the upload size limit.")

    content_hash = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(Source).where(
            Source.tenant_id == identity.tenant.id,
            Source.knowledge_space_id == knowledge_space_id,
            Source.content_hash == content_hash,
            Source.status == "active",
        )
    )
    if existing is not None:
        job = _latest_job(db, existing.id)
        if job is None:
            raise IngestionError(
                409,
                "source_state_invalid",
                "The matching source has no ingestion job.",
            )
        return SourceSubmission(existing, job, True)

    source_id = uuid4()
    document_id = uuid4()
    suffix = Path(original_filename or "").suffix.lower()
    raw_name = f"raw{suffix}" if suffix else "raw"
    object_key = (
        f"{identity.tenant.id}/{knowledge_space_id}/{source_id}/v1/{raw_name}"
    )
    source = Source(
        id=source_id,
        tenant_id=identity.tenant.id,
        knowledge_space_id=knowledge_space_id,
        created_by_user_id=identity.user.id,
        source_type=source_type.value,
        title=title.strip(),
        original_filename=original_filename,
        mime_type=mime_type,
        uri=uri,
        object_key=object_key,
        content_hash=content_hash,
        visibility=visibility,
        tags=tags or [],
        attributes=attributes or {},
        status="active",
        current_version=1,
    )
    document = Document(
        id=document_id,
        tenant_id=identity.tenant.id,
        source_id=source_id,
        version_number=1,
        raw_object_key=object_key,
        content_hash=content_hash,
        status=IngestionStatus.QUEUED.value,
    )
    job = _new_job(
        source=source,
        document=document,
        requested_by_user_id=identity.user.id,
        settings=settings,
    )
    source.documents.append(document)
    source.jobs.append(job)
    db.add(source)

    try:
        object_store.put_bytes(object_key, content, mime_type)
    except Exception as exc:
        db.rollback()
        raise IngestionError(
            503,
            "object_store_unavailable",
            "The original source could not be stored.",
        ) from exc

    record_audit(
        db,
        tenant_id=identity.tenant.id,
        actor_user_id=identity.user.id,
        action="source.create",
        target_type="source",
        target_id=str(source.id),
        subject=source.title,
        outcome="success",
        metadata=metadata,
        details={
            "knowledge_space_id": str(knowledge_space_id),
            "source_type": source_type.value,
            "content_hash_prefix": content_hash[:12],
        },
    )
    db.commit()
    return SourceSubmission(source, job, False)


def create_reindex_job(
    db: Session,
    *,
    settings: Settings,
    identity: AuthenticatedIdentity,
    metadata: RequestMetadata,
    source_id: UUID,
) -> SourceSubmission:
    source = _source_for_identity(db, identity, source_id, write=True)
    latest_version = db.scalar(
        select(func.max(Document.version_number)).where(Document.source_id == source.id)
    )
    version_number = int(latest_version or 0) + 1
    document = Document(
        id=uuid4(),
        tenant_id=source.tenant_id,
        source_id=source.id,
        version_number=version_number,
        raw_object_key=source.object_key,
        content_hash=source.content_hash,
        status=IngestionStatus.QUEUED.value,
    )
    job = _new_job(
        source=source,
        document=document,
        requested_by_user_id=identity.user.id,
        settings=settings,
    )
    source.documents.append(document)
    source.jobs.append(job)
    record_audit(
        db,
        tenant_id=identity.tenant.id,
        actor_user_id=identity.user.id,
        action="source.reindex",
        target_type="source",
        target_id=str(source.id),
        subject=source.title,
        outcome="success",
        metadata=metadata,
        details={"document_version": version_number, "job_id": str(job.id)},
    )
    db.commit()
    return SourceSubmission(source, job, False)


def transition_job(
    db: Session,
    job: IngestionJob,
    status: IngestionStatus,
    *,
    progress_percent: int,
    summary: str,
    error_code: str | None = None,
    error_message: str | None = None,
    event_metadata: dict[str, Any] | None = None,
) -> None:
    current = IngestionStatus(job.status)
    if status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid ingestion transition: {current.value} -> {status.value}.")
    now = utc_now()
    job.status = status.value
    job.progress_percent = max(0, min(progress_percent, 100))
    job.error_code = error_code
    job.error_message = error_message
    if status is IngestionStatus.EXTRACTING:
        job.attempt_count += 1
        job.started_at = now
    if status in {
        IngestionStatus.INDEXED,
        IngestionStatus.FAILED,
        IngestionStatus.CANCELLED,
        IngestionStatus.SUPERSEDED,
    }:
        job.finished_at = now
    job.events.append(
        IngestionJobEvent(
            tenant_id=job.tenant_id,
            status=status.value,
            progress_percent=job.progress_percent,
            attempt_number=job.attempt_count,
            summary=summary,
            error_code=error_code,
            attributes=event_metadata or {},
        )
    )
    db.commit()


def mark_job_queue_failure(db: Session, job_id: UUID) -> None:
    job = db.get(IngestionJob, job_id)
    if job is None or job.status != IngestionStatus.QUEUED.value:
        return
    transition_job(
        db,
        job,
        IngestionStatus.FAILED,
        progress_percent=0,
        summary="任务队列暂时不可用。",
        error_code="queue_unavailable",
        error_message="The ingestion job could not be queued.",
    )
    document = db.get(Document, job.document_id)
    if document is not None:
        document.status = IngestionStatus.FAILED.value
        db.commit()


def retry_job(
    db: Session,
    *,
    identity: AuthenticatedIdentity,
    metadata: RequestMetadata,
    job_id: UUID,
) -> IngestionJob:
    job = _job_for_identity(db, identity, job_id, write=True)
    if job.status not in {
        IngestionStatus.FAILED.value,
        IngestionStatus.CANCELLED.value,
    }:
        raise IngestionError(409, "job_not_retryable", "Only failed or cancelled jobs can retry.")
    if job.attempt_count >= job.max_attempts:
        raise IngestionError(409, "retry_limit_reached", "The ingestion retry limit was reached.")
    job.status = IngestionStatus.QUEUED.value
    job.progress_percent = 0
    job.error_code = None
    job.error_message = None
    job.cancel_requested = False
    job.queued_at = utc_now()
    job.started_at = None
    job.finished_at = None
    document = db.get(Document, job.document_id)
    if document is not None:
        document.status = IngestionStatus.QUEUED.value
    job.events.append(
        IngestionJobEvent(
            tenant_id=job.tenant_id,
            status=IngestionStatus.QUEUED.value,
            progress_percent=0,
            attempt_number=job.attempt_count,
            summary="入库任务已重新排队。",
        )
    )
    record_audit(
        db,
        tenant_id=identity.tenant.id,
        actor_user_id=identity.user.id,
        action="ingestion.retry",
        target_type="ingestion_job",
        target_id=str(job.id),
        outcome="success",
        metadata=metadata,
        details={"attempt_count": job.attempt_count},
    )
    db.commit()
    db.refresh(job)
    return job


def cancel_job(
    db: Session,
    *,
    identity: AuthenticatedIdentity,
    metadata: RequestMetadata,
    job_id: UUID,
) -> IngestionJob:
    job = _job_for_identity(db, identity, job_id, write=True)
    status = IngestionStatus(job.status)
    if status not in ACTIVE_INGESTION_STATUSES:
        raise IngestionError(409, "job_not_cancellable", "The ingestion job is already complete.")
    job.cancel_requested = True
    if status is IngestionStatus.QUEUED:
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
    record_audit(
        db,
        tenant_id=identity.tenant.id,
        actor_user_id=identity.user.id,
        action="ingestion.cancel",
        target_type="ingestion_job",
        target_id=str(job.id),
        outcome="success",
        metadata=metadata,
        details={"previous_status": status.value},
    )
    db.commit()
    db.refresh(job)
    return job


def get_job(
    db: Session,
    identity: AuthenticatedIdentity,
    job_id: UUID,
) -> IngestionJob:
    return _job_for_identity(db, identity, job_id)


def list_jobs(
    db: Session,
    identity: AuthenticatedIdentity,
    knowledge_space_id: UUID,
    *,
    limit: int = 50,
) -> list[IngestionJob]:
    require_space_access(db, identity, knowledge_space_id)
    return list(
        db.scalars(
            select(IngestionJob)
            .options(selectinload(IngestionJob.events))
            .where(
                IngestionJob.tenant_id == identity.tenant.id,
                IngestionJob.knowledge_space_id == knowledge_space_id,
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    )


def list_sources(
    db: Session,
    identity: AuthenticatedIdentity,
    knowledge_space_id: UUID,
) -> list[Source]:
    require_space_access(db, identity, knowledge_space_id)
    return list(
        db.scalars(
            select(Source)
            .where(
                Source.tenant_id == identity.tenant.id,
                Source.knowledge_space_id == knowledge_space_id,
                Source.status != "deleted",
            )
            .order_by(Source.updated_at.desc())
        )
    )


def get_source(
    db: Session,
    identity: AuthenticatedIdentity,
    source_id: UUID,
) -> Source:
    return _source_for_identity(db, identity, source_id)


def job_event_response(event: IngestionJobEvent) -> IngestionJobEventResponse:
    return IngestionJobEventResponse(
        id=event.id,
        status=IngestionStatus(event.status),
        progress_percent=event.progress_percent,
        attempt_number=event.attempt_number,
        summary=event.summary,
        error_code=event.error_code,
        metadata=event.attributes,
        created_at=event.created_at,
    )


def ingestion_job_response(job: IngestionJob) -> IngestionJobResponse:
    return IngestionJobResponse(
        id=job.id,
        source_id=job.source_id,
        document_id=job.document_id,
        status=IngestionStatus(job.status),
        progress_percent=job.progress_percent,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        error_code=job.error_code,
        error_message=job.error_message,
        correlation_id=job.correlation_id,
        cancel_requested=job.cancel_requested,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        events=[job_event_response(event) for event in job.events],
    )


def _source_summary(db: Session, source: Source) -> SourceSummaryResponse:
    latest_job = _latest_job(db, source.id)
    return SourceSummaryResponse(
        id=source.id,
        knowledge_space_id=source.knowledge_space_id,
        source_type=SourceType(source.source_type),
        title=source.title,
        original_filename=source.original_filename,
        mime_type=source.mime_type,
        uri=source.uri,
        content_hash=source.content_hash,
        visibility=source.visibility,
        tags=source.tags,
        status=source.status,
        current_version=source.current_version,
        latest_job_status=IngestionStatus(latest_job.status) if latest_job else None,
        latest_job_progress=latest_job.progress_percent if latest_job else None,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def source_summary_response(db: Session, source: Source) -> SourceSummaryResponse:
    return _source_summary(db, source)


def source_detail_response(db: Session, source: Source) -> SourceDetailResponse:
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.source_id == source.id)
            .order_by(Document.version_number.desc())
        )
    )
    counts = dict(
        db.execute(
            select(Chunk.document_id, func.count(Chunk.id))
            .where(Chunk.document_id.in_([document.id for document in documents]))
            .group_by(Chunk.document_id)
        ).all()
    ) if documents else {}
    latest_job = _latest_job(db, source.id)
    summary = _source_summary(db, source)
    return SourceDetailResponse(
        **summary.model_dump(),
        metadata=source.attributes,
        documents=[
            DocumentVersionResponse(
                id=document.id,
                version_number=document.version_number,
                status=IngestionStatus(document.status),
                is_active=document.is_active,
                language=document.language,
                chunk_count=int(counts.get(document.id, 0)),
                content_hash=document.content_hash,
                created_at=document.created_at,
                indexed_at=document.indexed_at,
                superseded_at=document.superseded_at,
            )
            for document in documents
        ],
        latest_job=ingestion_job_response(latest_job) if latest_job else None,
    )


def source_submission_response(
    db: Session,
    submission: SourceSubmission,
) -> SourceSubmissionResponse:
    return SourceSubmissionResponse(
        source=source_summary_response(db, submission.source),
        job=ingestion_job_response(submission.job),
        deduplicated=submission.deduplicated,
    )
