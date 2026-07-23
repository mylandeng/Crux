from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from curx.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(32))
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tenant: Mapped[Tenant] = relationship()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        Index("ix_users_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    role_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("roles.id"))
    username: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    authorization_version: Mapped[int] = mapped_column(Integer, default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tenant: Mapped[Tenant] = relationship()
    role: Mapped[Role] = relationship()
    space_grants: Mapped[list[UserKnowledgeSpaceGrant]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_spaces"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_spaces_tenant_name"),
        Index("ix_spaces_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(32), default="private")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    icon: Mapped[str] = mapped_column(String(48), default="book-open")
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    health_percent: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    tenant: Mapped[Tenant] = relationship()
    grants: Mapped[list[UserKnowledgeSpaceGrant]] = relationship(
        back_populates="space",
        cascade="all, delete-orphan",
    )
    sources: Mapped[list[Source]] = relationship(
        back_populates="knowledge_space",
        cascade="all, delete-orphan",
    )


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_space_id",
            "content_hash",
            "status",
            name="uq_sources_space_hash_status",
        ),
        Index("ix_sources_space_status", "knowledge_space_id", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    knowledge_space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(24), index=True)
    title: Mapped[str] = mapped_column(String(240))
    original_filename: Mapped[str | None] = mapped_column(String(240))
    mime_type: Mapped[str] = mapped_column(String(160))
    uri: Mapped[str | None] = mapped_column(String(1024))
    object_key: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    visibility: Mapped[str] = mapped_column(String(32), default="space")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    tenant: Mapped[Tenant] = relationship()
    knowledge_space: Mapped[KnowledgeSpace] = relationship(back_populates="sources")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    documents: Mapped[list[Document]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="Document.version_number",
    )
    jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("source_id", "version_number", name="uq_documents_source_version"),
        Index("ix_documents_source_active", "source_id", "is_active", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer)
    raw_object_key: Mapped[str] = mapped_column(String(1024))
    normalized_markdown: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(32), default="und")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    source: Mapped[Source] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.ordinal",
    )
    jobs: Mapped[list[IngestionJob]] = relationship(back_populates="document")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_ordinal"),
        Index("ix_chunks_retrieval_scope", "tenant_id", "knowledge_space_id", "is_active"),
        Index("ix_chunks_source_active", "source_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    knowledge_space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        index=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    heading_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    page_number: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(512))
    visibility: Mapped[str] = mapped_column(String(32), default="space")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    document: Mapped[Document] = relationship(back_populates="chunks")
    source: Mapped[Source] = relationship()
    knowledge_space: Mapped[KnowledgeSpace] = relationship()
    embeddings: Mapped[list[ChunkEmbedding]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
    )


class EmbeddingProfile(Base):
    __tablename__ = "embedding_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fingerprint", name="uq_embedding_profiles_fingerprint"),
        Index("ix_embedding_profiles_enabled", "tenant_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(48))
    model_name: Mapped[str] = mapped_column(String(160))
    dimension: Mapped[int] = mapped_column(Integer)
    distance_metric: Mapped[str] = mapped_column(String(24), default="cosine")
    fingerprint: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tenant: Mapped[Tenant] = relationship()
    embeddings: Mapped[list[ChunkEmbedding]] = relationship(back_populates="profile")


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_profile_id", name="uq_chunk_embedding_profile"),
        Index("ix_chunk_embeddings_profile", "embedding_profile_id", "chunk_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("chunks.id", ondelete="CASCADE"),
        index=True,
    )
    embedding_profile_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("embedding_profiles.id", ondelete="RESTRICT"),
        index=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    chunk: Mapped[Chunk] = relationship(back_populates="embeddings")
    profile: Mapped[EmbeddingProfile] = relationship(back_populates="embeddings")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_space_status", "knowledge_space_id", "status", "created_at"),
        Index("ix_ingestion_jobs_source_created", "source_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    knowledge_space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        index=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    source: Mapped[Source] = relationship(back_populates="jobs")
    document: Mapped[Document] = relationship(back_populates="jobs")
    requested_by: Mapped[User | None] = relationship()
    events: Mapped[list[IngestionJobEvent]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="IngestionJobEvent.created_at",
    )


class IngestionJobEvent(Base):
    __tablename__ = "ingestion_job_events"
    __table_args__ = (Index("ix_ingestion_job_events_job_created", "job_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), index=True)
    progress_percent: Mapped[int] = mapped_column(Integer)
    attempt_number: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(320))
    error_code: Mapped[str | None] = mapped_column(String(80))
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[IngestionJob] = relationship(back_populates="events")


class UserKnowledgeSpaceGrant(Base):
    __tablename__ = "user_knowledge_space_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_space_id", name="uq_user_space_grant"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    knowledge_space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        index=True,
    )
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="space_grants")
    space: Mapped[KnowledgeSpace] = relationship(back_populates="grants")


class AccessKey(Base):
    __tablename__ = "access_keys"
    __table_args__ = (
        Index("ix_access_keys_tenant_status", "tenant_id", "revoked_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(256))
    label: Mapped[str] = mapped_column(String(120))
    granted_role: Mapped[str] = mapped_column(String(32), default="member")
    all_spaces: Mapped[bool] = mapped_column(Boolean, default=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    authorization_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tenant: Mapped[Tenant] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    space_grants: Mapped[list[AccessKeyKnowledgeSpaceGrant]] = relationship(
        back_populates="access_key",
        cascade="all, delete-orphan",
    )
    binding: Mapped[KeyBinding | None] = relationship(
        back_populates="access_key",
        cascade="all, delete-orphan",
        uselist=False,
    )


class AccessKeyKnowledgeSpaceGrant(Base):
    __tablename__ = "access_key_knowledge_space_grants"
    __table_args__ = (
        UniqueConstraint(
            "access_key_id",
            "knowledge_space_id",
            name="uq_access_key_space_grant",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    access_key_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("access_keys.id", ondelete="CASCADE"),
        index=True,
    )
    knowledge_space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    access_key: Mapped[AccessKey] = relationship(back_populates="space_grants")
    space: Mapped[KnowledgeSpace] = relationship()


class KeyBinding(Base):
    __tablename__ = "key_bindings"
    __table_args__ = (
        UniqueConstraint("access_key_id", name="uq_key_bindings_access_key"),
        Index("ix_key_bindings_user_status", "user_id", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    access_key_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("access_keys.id", ondelete="CASCADE"),
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    authorization_version: Mapped[int] = mapped_column(Integer, default=1)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    access_key: Mapped[AccessKey] = relationship(back_populates="binding")
    user: Mapped[User] = relationship()
    sessions: Mapped[list[BrowserSession]] = relationship(
        back_populates="binding",
        cascade="all, delete-orphan",
    )


class BrowserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_status", "user_id", "revoked_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    key_binding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("key_bindings.id", ondelete="CASCADE"),
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_authorization_version: Mapped[int] = mapped_column(Integer)
    binding_authorization_version: Mapped[int] = mapped_column(Integer)
    access_key_authorization_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship()
    binding: Mapped[KeyBinding] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_logs_auth_failures", "action", "outcome", "subject", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="SET NULL"),
        index=True,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(64))
    subject: Mapped[str | None] = mapped_column(String(160), index=True)
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )

    tenant: Mapped[Tenant | None] = relationship()
    actor: Mapped[User | None] = relationship()
