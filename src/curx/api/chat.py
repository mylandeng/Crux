from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from curx.api.deps import ChatIdentity
from curx.core.config import Settings, get_settings
from curx.domain.schemas import AnswerResponse, ChatAnswerRequest
from curx.services.chat_llm import answer_chat, stream_chat

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/answer", response_model=AnswerResponse)
async def answer(
    payload: ChatAnswerRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    _identity: ChatIdentity,
) -> AnswerResponse:
    return await answer_chat(payload, settings)


@router.post("/stream")
async def stream(
    payload: ChatAnswerRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    _identity: ChatIdentity,
) -> StreamingResponse:
    return StreamingResponse(
        stream_chat(payload, settings),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
