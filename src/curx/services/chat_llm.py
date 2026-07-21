import json
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from fastapi import HTTPException, status
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from curx.core.config import Settings
from curx.domain.schemas import (
    AnswerEvent,
    AnswerEventType,
    AnswerResponse,
    ChatAnswerRequest,
    ChatRole,
)


def build_chat_model(settings: Settings) -> BaseChatModel:
    provider = settings.model_provider.strip().lower()
    model_kwargs: dict[str, Any] = {
        "model": settings.model_name,
        "temperature": settings.model_temperature,
    }

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs = dict(model_kwargs)
        if settings.model_api_key:
            kwargs["api_key"] = settings.model_api_key
        if settings.model_base_url:
            kwargs["base_url"] = settings.model_base_url
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs = dict(model_kwargs)
        if settings.model_api_key:
            kwargs["api_key"] = settings.model_api_key
        return ChatAnthropic(**kwargs)

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = dict(model_kwargs)
        if settings.model_api_key:
            kwargs["google_api_key"] = settings.model_api_key
        return ChatGoogleGenerativeAI(**kwargs)

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        kwargs = dict(model_kwargs)
        if settings.model_base_url:
            kwargs["base_url"] = settings.model_base_url
        return ChatOllama(**kwargs)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Unsupported CURX_MODEL_PROVIDER. "
            "Use one of: openai, anthropic, google, ollama."
        ),
    )


def to_langchain_messages(payload: ChatAnswerRequest) -> list[BaseMessage]:
    role_map = {
        ChatRole.system: SystemMessage,
        ChatRole.user: HumanMessage,
        ChatRole.assistant: AIMessage,
    }
    return [role_map[message.role](content=message.content) for message in payload.messages]


def message_content_to_text(content: str | list[Any]) -> str:
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def answer_chat(payload: ChatAnswerRequest, settings: Settings) -> AnswerResponse:
    started = perf_counter()
    model = build_chat_model(settings)
    messages = to_langchain_messages(payload)

    try:
        response = await model.ainvoke(messages)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Model provider request failed: {exc}",
        ) from exc

    duration_ms = max(1, int((perf_counter() - started) * 1000))
    answer = message_content_to_text(response.content)
    if not answer:
        answer = "模型没有返回可展示的文本内容。"

    return AnswerResponse(
        answer=answer,
        confidence="模型",
        handoff_required=False,
        events=[
            AnswerEvent(
                type=AnswerEventType.started,
                label="理解问题",
                summary="已接收当前对话上下文。",
                duration_ms=1,
            ),
            AnswerEvent(
                type=AnswerEventType.generating,
                label="调用模型",
                summary=f"使用 {settings.model_provider}/{settings.model_name} 生成回答。",
                duration_ms=duration_ms,
            ),
            AnswerEvent(
                type=AnswerEventType.completed,
                label="回答完成",
                summary="本次回答未引用知识库证据。",
                duration_ms=1,
            ),
        ],
        citations=[],
        next_actions=["继续追问", "换个问法", "总结要点"],
    )


async def stream_chat(payload: ChatAnswerRequest, settings: Settings) -> AsyncIterator[str]:
    started = perf_counter()

    yield sse_event(
        AnswerEventType.started,
        {
            "type": AnswerEventType.started,
            "label": "理解问题",
            "summary": "已接收当前对话上下文。",
            "duration_ms": 1,
        },
    )

    try:
        model = build_chat_model(settings)
        messages = to_langchain_messages(payload)

        yield sse_event(
            AnswerEventType.generating,
            {
                "type": AnswerEventType.generating,
                "label": "调用模型",
                "summary": f"使用 {settings.model_provider}/{settings.model_name} 生成回答。",
                "duration_ms": 1,
            },
        )

        answer_parts: list[str] = []
        async for chunk in model.astream(messages):
            text = message_content_to_text(chunk.content)
            if not text:
                continue

            answer_parts.append(text)
            yield sse_event(
                AnswerEventType.delta,
                {
                    "type": AnswerEventType.delta,
                    "text": text,
                },
            )

        duration_ms = max(1, int((perf_counter() - started) * 1000))
        answer = "".join(answer_parts).strip() or "模型没有返回可展示的文本内容。"

        yield sse_event(
            AnswerEventType.completed,
            {
                "type": AnswerEventType.completed,
                "answer": answer,
                "confidence": "模型",
                "handoff_required": False,
                "events": [
                    {
                        "type": AnswerEventType.started,
                        "label": "理解问题",
                        "summary": "已接收当前对话上下文。",
                        "duration_ms": 1,
                        "safe_source_ids": [],
                    },
                    {
                        "type": AnswerEventType.generating,
                        "label": "调用模型",
                        "summary": (
                            f"使用 {settings.model_provider}/{settings.model_name} 生成回答。"
                        ),
                        "duration_ms": duration_ms,
                        "safe_source_ids": [],
                    },
                    {
                        "type": AnswerEventType.completed,
                        "label": "回答完成",
                        "summary": "本次回答未引用知识库证据。",
                        "duration_ms": 1,
                        "safe_source_ids": [],
                    },
                ],
                "citations": [],
                "next_actions": ["继续追问", "换个问法", "总结要点"],
            },
        )
    except Exception as exc:
        yield sse_event(
            AnswerEventType.failed,
            {
                "type": AnswerEventType.failed,
                "label": "生成失败",
                "summary": f"Model provider request failed: {exc}",
                "duration_ms": max(1, int((perf_counter() - started) * 1000)),
            },
        )
