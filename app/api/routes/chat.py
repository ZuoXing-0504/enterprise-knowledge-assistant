import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.database import SessionDependency
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.infrastructure.rate_limit import RedisRateLimiter
from app.rag.errors import ChatServiceError
from app.schemas.chat import ChatRequest, ChatResponse, ConversationResponse, MessageResponse
from app.schemas.common import ApiResponse, PageResponse
from app.services.chat import ChatService

router = APIRouter(tags=["Chat"])


@router.post(
    "/knowledge-bases/{knowledge_base_id}/chat",
    response_model=ApiResponse[ChatResponse],
)
async def chat_with_knowledge_base(
    knowledge_base_id: UUID,
    payload: ChatRequest,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[ChatResponse]:
    await _enforce_chat_rate_limit(request, current_user.id)
    result = await ChatService(
        session,
        redis=getattr(request.app.state, "redis", None),
    ).ask(
        knowledge_base_id,
        current_user.id,
        payload,
    )
    return ApiResponse(data=result, request_id=request.state.request_id)


@router.post("/knowledge-bases/{knowledge_base_id}/chat/stream")
async def stream_chat_with_knowledge_base(
    knowledge_base_id: UUID,
    payload: ChatRequest,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> StreamingResponse:
    await _enforce_chat_rate_limit(request, current_user.id)
    service = ChatService(
        session,
        redis=getattr(request.app.state, "redis", None),
    )
    prepared = await service.prepare(
        knowledge_base_id,
        current_user.id,
        payload,
    )

    async def event_stream() -> AsyncIterator[str]:
        yield _sse_event(
            "metadata",
            {"request_id": request.state.request_id},
        )
        try:
            async for event in service.stream(prepared):
                yield _sse_event(
                    event.event,
                    {
                        **event.data,
                        "request_id": request.state.request_id,
                    },
                )
        except ChatServiceError as exc:
            error = ChatService.chat_app_error(exc)
            yield _sse_event(
                "error",
                {
                    "code": error.code,
                    "message": error.message,
                    "request_id": request.state.request_id,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/conversations",
    response_model=ApiResponse[PageResponse[ConversationResponse]],
)
async def list_conversations(
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[PageResponse[ConversationResponse]]:
    result = await ChatService(session).list_conversations(
        current_user.id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result, request_id=request.state.request_id)


async def _enforce_chat_rate_limit(request: Request, user_id: UUID) -> None:
    settings = get_settings()
    result = await RedisRateLimiter(getattr(request.app.state, "redis", None)).check(
        scope="chat",
        user_id=user_id,
        limit=settings.chat_rate_limit_requests,
        window_seconds=settings.chat_rate_limit_window_seconds,
    )
    if not result.allowed:
        raise AppError(
            code="rate_limit_exceeded",
            message="Too many chat requests",
            status_code=429,
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


def _sse_event(event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ApiResponse[PageResponse[MessageResponse]],
)
async def list_conversation_messages(
    conversation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ApiResponse[PageResponse[MessageResponse]]:
    result = await ChatService(session).list_messages(
        conversation_id,
        current_user.id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result, request_id=request.state.request_id)
