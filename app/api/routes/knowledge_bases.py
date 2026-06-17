from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.database import SessionDependency
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from app.services.knowledge_base import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Bases"])


@router.post(
    "",
    response_model=ApiResponse[KnowledgeBaseResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[KnowledgeBaseResponse]:
    knowledge_base = await KnowledgeBaseService(session).create(current_user.id, payload)
    return ApiResponse(
        data=KnowledgeBaseResponse.model_validate(knowledge_base),
        request_id=request.state.request_id,
    )


@router.get("", response_model=ApiResponse[PageResponse[KnowledgeBaseResponse]])
async def list_knowledge_bases(
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[PageResponse[KnowledgeBaseResponse]]:
    result = await KnowledgeBaseService(session).list(
        current_user.id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result, request_id=request.state.request_id)


@router.get("/{knowledge_base_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def get_knowledge_base(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[KnowledgeBaseResponse]:
    knowledge_base = await KnowledgeBaseService(session).get(
        knowledge_base_id,
        current_user.id,
    )
    return ApiResponse(
        data=KnowledgeBaseResponse.model_validate(knowledge_base),
        request_id=request.state.request_id,
    )


@router.patch("/{knowledge_base_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def update_knowledge_base(
    knowledge_base_id: UUID,
    payload: KnowledgeBaseUpdate,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[KnowledgeBaseResponse]:
    knowledge_base = await KnowledgeBaseService(session).update(
        knowledge_base_id,
        current_user.id,
        payload,
    )
    return ApiResponse(
        data=KnowledgeBaseResponse.model_validate(knowledge_base),
        request_id=request.state.request_id,
    )


@router.delete("/{knowledge_base_id}", response_model=ApiResponse[None])
async def delete_knowledge_base(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[None]:
    await KnowledgeBaseService(session).delete(knowledge_base_id, current_user.id)
    return ApiResponse(data=None, request_id=request.state.request_id)
