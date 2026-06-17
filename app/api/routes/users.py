from fastapi import APIRouter, Request

from app.api.dependencies.auth import CurrentUser
from app.schemas.common import ApiResponse
from app.schemas.user import UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=ApiResponse[UserResponse])
async def get_me(current_user: CurrentUser, request: Request) -> ApiResponse[UserResponse]:
    return ApiResponse(
        data=UserResponse.model_validate(current_user),
        request_id=request.state.request_id,
    )
