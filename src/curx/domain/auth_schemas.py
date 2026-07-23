from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RoleName = Literal["member", "operator", "admin"]


class BindAccessKeyRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    access_key: str = Field(min_length=20, max_length=256)


class TenantSummary(BaseModel):
    id: UUID
    name: str
    slug: str


class CurrentUserResponse(BaseModel):
    id: UUID
    username: str
    display_name: str
    role: RoleName
    tenant: TenantSummary


class AuthSessionResponse(BaseModel):
    user: CurrentUserResponse
    expires_at: datetime


class SessionStatusResponse(BaseModel):
    authenticated: bool


class KnowledgeSpaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    visibility: Literal["private", "tenant"] = "private"
    color: str = Field(default="#2563eb", pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str = Field(default="book-open", min_length=1, max_length=48)


class KnowledgeSpaceResponse(BaseModel):
    id: UUID
    name: str
    description: str
    visibility: str
    status: str
    color: str
    icon: str
    document_count: int
    health_percent: int
    can_read: bool
    can_write: bool
    can_manage: bool


class AccessKeyCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    granted_role: RoleName = "member"
    active_from: datetime | None = None
    expires_at: datetime
    all_spaces: bool = False
    knowledge_space_ids: list[UUID] = Field(default_factory=list)


class AccessKeyCreatedResponse(BaseModel):
    id: UUID
    prefix: str
    access_key: str
    label: str
    granted_role: RoleName
    active_from: datetime
    expires_at: datetime
    all_spaces: bool
    knowledge_space_ids: list[UUID]
    status: str


class AccessKeySummaryResponse(BaseModel):
    id: UUID
    prefix: str
    label: str
    granted_role: RoleName
    active_from: datetime
    expires_at: datetime
    revoked_at: datetime | None
    all_spaces: bool
    knowledge_space_ids: list[UUID]
    bound_username: str | None
    status: str
    created_at: datetime


class WorkspaceResponse(BaseModel):
    current_user: CurrentUserResponse
    spaces: list[KnowledgeSpaceResponse]
