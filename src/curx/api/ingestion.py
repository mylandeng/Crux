from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status

from curx.api.deps import (
    AppIngestionJobQueue,
    AppObjectStore,
    AppSettings,
    CurrentIdentity,
    DatabaseSession,
    RequestInfo,
)
from curx.domain.ingestion_schemas import (
    FaqSourceCreateRequest,
    IngestionJobResponse,
    SourceDetailResponse,
    SourceSubmissionResponse,
    SourceSummaryResponse,
    SourceType,
    TextSourceCreateRequest,
)
from curx.services.content_loaders import ContentLoadError, detect_source_type
from curx.services.ingestion_service import (
    IngestionError,
    cancel_job,
    create_reindex_job,
    get_job,
    get_source,
    ingestion_job_response,
    list_jobs,
    list_sources,
    mark_job_queue_failure,
    retry_job,
    source_detail_response,
    source_submission_response,
    source_summary_response,
    submit_source,
)

router = APIRouter(tags=["knowledge-ingestion"])


def ingestion_http_error(error: IngestionError | ContentLoadError) -> HTTPException:
    status_code = error.status_code if isinstance(error, IngestionError) else 422
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )


async def enqueue_or_fail(
    *,
    queue: AppIngestionJobQueue,
    db: DatabaseSession,
    job_id: UUID,
) -> None:
    try:
        await queue.enqueue(job_id)
    except Exception as exc:
        mark_job_queue_failure(db, job_id)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "queue_unavailable",
                "message": "The ingestion job could not be queued.",
            },
        ) from exc


@router.get(
    "/knowledge-spaces/{knowledge_space_id}/sources",
    response_model=list[SourceSummaryResponse],
)
def source_list(
    knowledge_space_id: UUID,
    db: DatabaseSession,
    identity: CurrentIdentity,
) -> list[SourceSummaryResponse]:
    try:
        sources = list_sources(db, identity, knowledge_space_id)
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    return [source_summary_response(db, source) for source in sources]


@router.get(
    "/knowledge-spaces/{knowledge_space_id}/ingestion-jobs",
    response_model=list[IngestionJobResponse],
)
def ingestion_job_list(
    knowledge_space_id: UUID,
    db: DatabaseSession,
    identity: CurrentIdentity,
    limit: int = 50,
) -> list[IngestionJobResponse]:
    try:
        jobs = list_jobs(db, identity, knowledge_space_id, limit=limit)
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    return [ingestion_job_response(job) for job in jobs]


@router.post(
    "/knowledge-spaces/{knowledge_space_id}/sources/upload",
    response_model=SourceSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_source(
    knowledge_space_id: UUID,
    response: Response,
    db: DatabaseSession,
    identity: CurrentIdentity,
    request_info: RequestInfo,
    settings: AppSettings,
    object_store: AppObjectStore,
    queue: AppIngestionJobQueue,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    visibility: Annotated[str, Form()] = "space",
    tags: Annotated[str, Form()] = "",
) -> SourceSubmissionResponse:
    filename = file.filename or "upload"
    try:
        source_type = detect_source_type(filename, file.content_type)
        content = await file.read(settings.ingestion_max_upload_bytes + 1)
        submission = submit_source(
            db,
            object_store=object_store,
            settings=settings,
            identity=identity,
            metadata=request_info,
            knowledge_space_id=knowledge_space_id,
            source_type=source_type,
            title=(title or filename).strip(),
            content=content,
            mime_type=file.content_type or "application/octet-stream",
            original_filename=filename,
            visibility=visibility,
            tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        )
    except (IngestionError, ContentLoadError) as exc:
        raise ingestion_http_error(exc) from exc
    finally:
        await file.close()

    if submission.deduplicated:
        response.status_code = status.HTTP_200_OK
    else:
        await enqueue_or_fail(queue=queue, db=db, job_id=submission.job.id)
    return source_submission_response(db, submission)


@router.post(
    "/knowledge-spaces/{knowledge_space_id}/sources/text",
    response_model=SourceSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_text_source(
    knowledge_space_id: UUID,
    payload: TextSourceCreateRequest,
    response: Response,
    db: DatabaseSession,
    identity: CurrentIdentity,
    request_info: RequestInfo,
    settings: AppSettings,
    object_store: AppObjectStore,
    queue: AppIngestionJobQueue,
) -> SourceSubmissionResponse:
    try:
        submission = submit_source(
            db,
            object_store=object_store,
            settings=settings,
            identity=identity,
            metadata=request_info,
            knowledge_space_id=knowledge_space_id,
            source_type=payload.source_type,
            title=payload.title,
            content=payload.content.encode("utf-8"),
            mime_type=(
                "text/markdown"
                if payload.source_type is SourceType.MARKDOWN
                else "text/html"
            ),
            uri=payload.uri,
            visibility=payload.visibility,
            tags=payload.tags,
            attributes=payload.metadata,
        )
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    if submission.deduplicated:
        response.status_code = status.HTTP_200_OK
    else:
        await enqueue_or_fail(queue=queue, db=db, job_id=submission.job.id)
    return source_submission_response(db, submission)


@router.post(
    "/knowledge-spaces/{knowledge_space_id}/sources/faq",
    response_model=SourceSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_faq_source(
    knowledge_space_id: UUID,
    payload: FaqSourceCreateRequest,
    response: Response,
    db: DatabaseSession,
    identity: CurrentIdentity,
    request_info: RequestInfo,
    settings: AppSettings,
    object_store: AppObjectStore,
    queue: AppIngestionJobQueue,
) -> SourceSubmissionResponse:
    markdown = "\n\n".join(
        [
            f"# {payload.title}",
            *(f"## {item.question}\n\n{item.answer}" for item in payload.items),
        ]
    )
    try:
        submission = submit_source(
            db,
            object_store=object_store,
            settings=settings,
            identity=identity,
            metadata=request_info,
            knowledge_space_id=knowledge_space_id,
            source_type=SourceType.FAQ,
            title=payload.title,
            content=markdown.encode("utf-8"),
            mime_type="text/markdown",
            visibility=payload.visibility,
            tags=payload.tags,
            attributes={**payload.metadata, "faq_count": len(payload.items)},
        )
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    if submission.deduplicated:
        response.status_code = status.HTTP_200_OK
    else:
        await enqueue_or_fail(queue=queue, db=db, job_id=submission.job.id)
    return source_submission_response(db, submission)


@router.get("/sources/{source_id}", response_model=SourceDetailResponse)
def source_detail(
    source_id: UUID,
    db: DatabaseSession,
    identity: CurrentIdentity,
) -> SourceDetailResponse:
    try:
        source = get_source(db, identity, source_id)
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    return source_detail_response(db, source)


@router.post(
    "/sources/{source_id}/reindex",
    response_model=SourceSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_source(
    source_id: UUID,
    db: DatabaseSession,
    identity: CurrentIdentity,
    request_info: RequestInfo,
    settings: AppSettings,
    queue: AppIngestionJobQueue,
) -> SourceSubmissionResponse:
    try:
        submission = create_reindex_job(
            db,
            settings=settings,
            identity=identity,
            metadata=request_info,
            source_id=source_id,
        )
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    await enqueue_or_fail(queue=queue, db=db, job_id=submission.job.id)
    return source_submission_response(db, submission)


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobResponse)
def ingestion_job_detail(
    job_id: UUID,
    db: DatabaseSession,
    identity: CurrentIdentity,
) -> IngestionJobResponse:
    try:
        job = get_job(db, identity, job_id)
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    return ingestion_job_response(job)


@router.post("/ingestion-jobs/{job_id}/retry", response_model=IngestionJobResponse)
async def retry_ingestion_job(
    job_id: UUID,
    db: DatabaseSession,
    identity: CurrentIdentity,
    request_info: RequestInfo,
    queue: AppIngestionJobQueue,
) -> IngestionJobResponse:
    try:
        job = retry_job(
            db,
            identity=identity,
            metadata=request_info,
            job_id=job_id,
        )
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    await enqueue_or_fail(queue=queue, db=db, job_id=job.id)
    return ingestion_job_response(job)


@router.post("/ingestion-jobs/{job_id}/cancel", response_model=IngestionJobResponse)
def cancel_ingestion_job(
    job_id: UUID,
    db: DatabaseSession,
    identity: CurrentIdentity,
    request_info: RequestInfo,
) -> IngestionJobResponse:
    try:
        job = cancel_job(
            db,
            identity=identity,
            metadata=request_info,
            job_id=job_id,
        )
    except IngestionError as exc:
        raise ingestion_http_error(exc) from exc
    return ingestion_job_response(job)
