from fastapi import APIRouter

from curx.domain.schemas import AnswerRequest, AnswerResponse, WorkspaceSnapshot
from curx.services.demo_workspace import answer_question, get_workspace_snapshot

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/workspace", response_model=WorkspaceSnapshot)
def workspace() -> WorkspaceSnapshot:
    return get_workspace_snapshot()


@router.post("/answer", response_model=AnswerResponse)
def answer(payload: AnswerRequest) -> AnswerResponse:
    return answer_question(payload.question)
