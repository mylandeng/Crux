from uuid import UUID

from fastapi import APIRouter

from curx.api.deps import (
    AdminIdentity,
    DatabaseSession,
    RequestInfo,
    identity_error,
)
from curx.domain.auth_schemas import (
    AccessKeyCreatedResponse,
    AccessKeyCreateRequest,
    AccessKeySummaryResponse,
    KnowledgeSpaceCreateRequest,
    KnowledgeSpaceResponse,
)
from curx.services.identity_service import (
    IdentityError,
    access_key_status,
    create_access_key,
    create_knowledge_space,
    list_access_keys,
    list_user_spaces,
    revoke_access_key,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def access_key_summary(access_key) -> AccessKeySummaryResponse:
    binding = access_key.binding
    return AccessKeySummaryResponse(
        id=access_key.id,
        prefix=access_key.prefix,
        label=access_key.label,
        granted_role=access_key.granted_role,
        active_from=access_key.active_from,
        expires_at=access_key.expires_at,
        revoked_at=access_key.revoked_at,
        all_spaces=access_key.all_spaces,
        knowledge_space_ids=[
            grant.knowledge_space_id for grant in access_key.space_grants
        ],
        bound_username=binding.user.username if binding and binding.user else None,
        status=access_key_status(access_key),
        created_at=access_key.created_at,
    )


@router.post("/access-keys", response_model=AccessKeyCreatedResponse, status_code=201)
def issue_access_key(
    payload: AccessKeyCreateRequest,
    identity: AdminIdentity,
    db: DatabaseSession,
    metadata: RequestInfo,
) -> AccessKeyCreatedResponse:
    try:
        access_key, raw_key = create_access_key(
            db,
            actor=identity,
            payload=payload,
            metadata=metadata,
        )
    except IdentityError as exc:
        raise identity_error(exc) from exc
    return AccessKeyCreatedResponse(
        id=access_key.id,
        prefix=access_key.prefix,
        access_key=raw_key,
        label=access_key.label,
        granted_role=access_key.granted_role,
        active_from=access_key.active_from,
        expires_at=access_key.expires_at,
        all_spaces=access_key.all_spaces,
        knowledge_space_ids=payload.knowledge_space_ids,
        status=access_key_status(access_key),
    )


@router.get("/access-keys", response_model=list[AccessKeySummaryResponse])
def access_keys(
    identity: AdminIdentity,
    db: DatabaseSession,
) -> list[AccessKeySummaryResponse]:
    return [access_key_summary(item) for item in list_access_keys(db, identity)]


@router.delete(
    "/access-keys/{access_key_id}",
    response_model=AccessKeySummaryResponse,
)
def revoke_key(
    access_key_id: UUID,
    identity: AdminIdentity,
    db: DatabaseSession,
    metadata: RequestInfo,
) -> AccessKeySummaryResponse:
    try:
        access_key = revoke_access_key(
            db,
            actor=identity,
            access_key_id=access_key_id,
            metadata=metadata,
        )
    except IdentityError as exc:
        raise identity_error(exc) from exc
    return access_key_summary(access_key)


@router.post(
    "/knowledge-spaces",
    response_model=KnowledgeSpaceResponse,
    status_code=201,
)
def add_knowledge_space(
    payload: KnowledgeSpaceCreateRequest,
    identity: AdminIdentity,
    db: DatabaseSession,
    metadata: RequestInfo,
) -> KnowledgeSpaceResponse:
    try:
        created = create_knowledge_space(
            db,
            actor=identity,
            payload=payload,
            metadata=metadata,
        )
    except IdentityError as exc:
        raise identity_error(exc) from exc
    return KnowledgeSpaceResponse(
        id=created.id,
        name=created.name,
        description=created.description,
        visibility=created.visibility,
        status=created.status,
        color=created.color,
        icon=created.icon,
        document_count=created.document_count,
        health_percent=created.health_percent,
        can_read=True,
        can_write=True,
        can_manage=True,
    )


@router.get("/knowledge-spaces", response_model=list[KnowledgeSpaceResponse])
def knowledge_spaces(
    identity: AdminIdentity,
    db: DatabaseSession,
) -> list[KnowledgeSpaceResponse]:
    return [
        KnowledgeSpaceResponse(
            id=space.id,
            name=space.name,
            description=space.description,
            visibility=space.visibility,
            status=space.status,
            color=space.color,
            icon=space.icon,
            document_count=space.document_count,
            health_percent=space.health_percent,
            can_read=grant.can_read,
            can_write=grant.can_write,
            can_manage=grant.can_manage,
        )
        for space, grant in list_user_spaces(db, identity)
    ]
