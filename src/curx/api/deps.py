from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from curx.core.config import Settings, get_settings
from curx.core.database import get_db
from curx.domain.auth_schemas import CurrentUserResponse, TenantSummary
from curx.services.identity_service import (
    AuthenticatedIdentity,
    IdentityError,
    RequestMetadata,
    authenticate_session,
    record_audit,
)
from curx.services.job_queue import IngestionJobQueue
from curx.services.object_store import ObjectStore

DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def request_metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


RequestInfo = Annotated[RequestMetadata, Depends(request_metadata)]


def identity_error(exc: IdentityError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def current_user_response(identity: AuthenticatedIdentity) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=identity.user.id,
        username=identity.user.username,
        display_name=identity.user.display_name,
        role=identity.role.name,
        tenant=TenantSummary(
            id=identity.tenant.id,
            name=identity.tenant.name,
            slug=identity.tenant.slug,
        ),
    )


def get_current_identity(
    request: Request,
    db: DatabaseSession,
    settings: AppSettings,
) -> AuthenticatedIdentity:
    raw_session_token = request.cookies.get(settings.session_cookie_name)
    if not raw_session_token:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "Authentication is required."},
        )
    try:
        return authenticate_session(
            db,
            raw_session_token=raw_session_token,
            metadata=request_metadata(request),
        )
    except IdentityError as exc:
        raise identity_error(exc) from exc


CurrentIdentity = Annotated[AuthenticatedIdentity, Depends(get_current_identity)]


def get_chat_identity(
    request: Request,
    db: DatabaseSession,
    settings: AppSettings,
) -> AuthenticatedIdentity | None:
    if not settings.auth_required:
        return None
    return get_current_identity(request, db, settings)


ChatIdentity = Annotated[AuthenticatedIdentity | None, Depends(get_chat_identity)]


def get_object_store(request: Request) -> ObjectStore:
    return request.app.state.object_store


def get_ingestion_job_queue(request: Request) -> IngestionJobQueue:
    return request.app.state.ingestion_job_queue


AppObjectStore = Annotated[ObjectStore, Depends(get_object_store)]
AppIngestionJobQueue = Annotated[IngestionJobQueue, Depends(get_ingestion_job_queue)]


def require_admin(
    request: Request,
    identity: CurrentIdentity,
    db: DatabaseSession,
) -> AuthenticatedIdentity:
    if identity.role.name != "admin":
        record_audit(
            db,
            tenant_id=identity.tenant.id,
            actor_user_id=identity.user.id,
            action="authorization.denied",
            target_type="admin_api",
            subject=identity.user.username,
            outcome="denied",
            metadata=request_metadata(request),
            details={"required_role": "admin", "actual_role": identity.role.name},
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail={"code": "admin_required", "message": "Administrator access is required."},
        )
    return identity


AdminIdentity = Annotated[AuthenticatedIdentity, Depends(require_admin)]
