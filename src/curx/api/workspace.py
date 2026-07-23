from fastapi import APIRouter

from curx.api.deps import CurrentIdentity, DatabaseSession, current_user_response
from curx.domain.auth_schemas import KnowledgeSpaceResponse, WorkspaceResponse
from curx.services.identity_service import list_user_spaces

router = APIRouter(tags=["workspace"])


@router.get("/workspace", response_model=WorkspaceResponse)
def workspace(identity: CurrentIdentity, db: DatabaseSession) -> WorkspaceResponse:
    spaces = [
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
    return WorkspaceResponse(
        current_user=current_user_response(identity),
        spaces=spaces,
    )
