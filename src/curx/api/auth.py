from fastapi import APIRouter, Request, Response

from curx.api.deps import (
    AppSettings,
    CurrentIdentity,
    DatabaseSession,
    RequestInfo,
    current_user_response,
    identity_error,
)
from curx.domain.auth_schemas import (
    AuthSessionResponse,
    BindAccessKeyRequest,
    CurrentUserResponse,
    SessionStatusResponse,
)
from curx.services.identity_service import (
    IdentityError,
    authenticate_session,
    bind_access_key,
    logout,
    utc_now,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/bind", response_model=AuthSessionResponse)
def bind(
    payload: BindAccessKeyRequest,
    response: Response,
    db: DatabaseSession,
    settings: AppSettings,
    metadata: RequestInfo,
) -> AuthSessionResponse:
    try:
        bound = bind_access_key(
            db,
            username=payload.username,
            display_name=payload.display_name,
            raw_access_key=payload.access_key,
            settings=settings,
            metadata=metadata,
        )
    except IdentityError as exc:
        raise identity_error(exc) from exc

    expires_at = bound.identity.browser_session.expires_at
    max_age = max(0, int((expires_at - utc_now()).total_seconds()))
    response.set_cookie(
        key=settings.session_cookie_name,
        value=bound.raw_session_token,
        max_age=max_age,
        expires=expires_at,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return AuthSessionResponse(
        user=current_user_response(bound.identity),
        expires_at=expires_at,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(identity: CurrentIdentity) -> CurrentUserResponse:
    return current_user_response(identity)


@router.get("/session", response_model=SessionStatusResponse)
def session_status(
    request: Request,
    db: DatabaseSession,
    settings: AppSettings,
    metadata: RequestInfo,
) -> SessionStatusResponse:
    raw_session_token = request.cookies.get(settings.session_cookie_name)
    if not raw_session_token:
        return SessionStatusResponse(authenticated=False)
    try:
        authenticate_session(
            db,
            raw_session_token=raw_session_token,
            metadata=metadata,
        )
    except IdentityError:
        return SessionStatusResponse(authenticated=False)
    return SessionStatusResponse(authenticated=True)


@router.post("/logout", status_code=204)
def sign_out(
    response: Response,
    identity: CurrentIdentity,
    db: DatabaseSession,
    settings: AppSettings,
    metadata: RequestInfo,
) -> None:
    logout(db, identity=identity, metadata=metadata)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
