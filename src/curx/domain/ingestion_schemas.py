from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SourceType(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"
    DOCX = "docx"
    FAQ = "faq"


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    NORMALIZING = "normalizing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


ACTIVE_INGESTION_STATUSES = {
    IngestionStatus.QUEUED,
    IngestionStatus.EXTRACTING,
    IngestionStatus.NORMALIZING,
    IngestionStatus.CHUNKING,
    IngestionStatus.EMBEDDING,
}

TERMINAL_INGESTION_STATUSES = {
    IngestionStatus.INDEXED,
    IngestionStatus.FAILED,
    IngestionStatus.CANCELLED,
    IngestionStatus.SUPERSEDED,
}


class TextSourceCreateRequest(BaseModel):
    title: NonEmptyText = Field(max_length=240)
    source_type: SourceType
    content: NonEmptyText
    uri: str | None = Field(default=None, max_length=1024)
    visibility: str = Field(default="space", max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=30)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_type")
    @classmethod
    def text_source_type(cls, value: SourceType) -> SourceType:
        if value not in {SourceType.MARKDOWN, SourceType.HTML}:
            raise ValueError("Text sources must be markdown or html.")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class FaqItemRequest(BaseModel):
    question: NonEmptyText = Field(max_length=1000)
    answer: NonEmptyText


class FaqSourceCreateRequest(BaseModel):
    title: NonEmptyText = Field(max_length=240)
    items: list[FaqItemRequest] = Field(min_length=1, max_length=500)
    visibility: str = Field(default="space", max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=30)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class IngestionJobEventResponse(BaseModel):
    id: UUID
    status: IngestionStatus
    progress_percent: int
    attempt_number: int
    summary: str
    error_code: str | None
    metadata: dict[str, Any]
    created_at: datetime


class IngestionJobResponse(BaseModel):
    id: UUID
    source_id: UUID
    document_id: UUID
    status: IngestionStatus
    progress_percent: int
    attempt_count: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    correlation_id: str
    cancel_requested: bool
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[IngestionJobEventResponse] = Field(default_factory=list)


class DocumentVersionResponse(BaseModel):
    id: UUID
    version_number: int
    status: IngestionStatus
    is_active: bool
    language: str
    chunk_count: int
    content_hash: str
    created_at: datetime
    indexed_at: datetime | None
    superseded_at: datetime | None


class SourceSummaryResponse(BaseModel):
    id: UUID
    knowledge_space_id: UUID
    source_type: SourceType
    title: str
    original_filename: str | None
    mime_type: str
    uri: str | None
    content_hash: str
    visibility: str
    tags: list[str]
    status: str
    current_version: int
    latest_job_status: IngestionStatus | None
    latest_job_progress: int | None
    created_at: datetime
    updated_at: datetime


class SourceDetailResponse(SourceSummaryResponse):
    metadata: dict[str, Any]
    documents: list[DocumentVersionResponse]
    latest_job: IngestionJobResponse | None


class SourceSubmissionResponse(BaseModel):
    source: SourceSummaryResponse
    job: IngestionJobResponse
    deduplicated: bool

