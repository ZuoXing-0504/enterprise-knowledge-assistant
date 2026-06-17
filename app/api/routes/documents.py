from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, Request, UploadFile, status

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.database import SessionDependency
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.document import DocumentResponse
from app.services.document import DocumentService

router = APIRouter(tags=["Documents"])


@router.post(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=ApiResponse[DocumentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    knowledge_base_id: UUID,
    file: Annotated[UploadFile, File(...)],
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[DocumentResponse]:
    document = await DocumentService(session).upload(
        knowledge_base_id,
        current_user.id,
        file,
    )
    return ApiResponse(
        data=DocumentResponse.model_validate(document),
        request_id=request.state.request_id,
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=ApiResponse[PageResponse[DocumentResponse]],
)
async def list_documents(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[PageResponse[DocumentResponse]]:
    result = await DocumentService(session).list(
        knowledge_base_id,
        current_user.id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result, request_id=request.state.request_id)


@router.get("/documents/{document_id}", response_model=ApiResponse[DocumentResponse])
async def get_document(
    document_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[DocumentResponse]:
    document = await DocumentService(session).get(document_id, current_user.id)
    return ApiResponse(
        data=DocumentResponse.model_validate(document),
        request_id=request.state.request_id,
    )


@router.delete("/documents/{document_id}", response_model=ApiResponse[None])
async def delete_document(
    document_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[None]:
    await DocumentService(session).delete(document_id, current_user.id)
    return ApiResponse(data=None, request_id=request.state.request_id)
