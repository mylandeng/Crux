from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class IngestionStatus(StrEnum):
    queued = "queued"
    extracting = "extracting"
    normalizing = "normalizing"
    chunking = "chunking"
    embedding = "embedding"
    indexed = "indexed"
    failed = "failed"
    cancelled = "cancelled"
    superseded = "superseded"


class AnswerEventType(StrEnum):
    started = "answer.started"
    query_understood = "query.understood"
    retrieval_started = "retrieval.started"
    evidence_ready = "evidence.ready"
    generating = "answer.generating"
    completed = "answer.completed"
    failed = "answer.failed"


class KnowledgeSpace(BaseModel):
    id: UUID
    name: str
    description: str
    document_count: int = Field(ge=0)
    health_percent: int = Field(ge=0, le=100)
    visibility: str
    color: str
    icon: str


class SourceSummary(BaseModel):
    id: UUID
    title: str
    version: str
    page: int | None = None
    location: str
    excerpt: str
    relevance: str
    source_type: str
    updated_at: datetime


class AnswerEvent(BaseModel):
    type: AnswerEventType
    label: str
    summary: str
    duration_ms: int
    safe_source_ids: list[UUID] = Field(default_factory=list)


class Citation(BaseModel):
    order: int
    source_id: UUID
    title: str
    chunk_id: UUID
    page: int | None = None
    location: str
    excerpt: str
    score: float = Field(ge=0, le=1)


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    knowledge_space_id: UUID | None = None


class AnswerResponse(BaseModel):
    answer: str
    confidence: str
    handoff_required: bool
    events: list[AnswerEvent]
    citations: list[Citation]
    next_actions: list[str]


class WorkspaceSnapshot(BaseModel):
    current_user: str
    spaces: list[KnowledgeSpace]
    recent_questions: list[str]
    saved_questions: list[str]
    sources: list[SourceSummary]
