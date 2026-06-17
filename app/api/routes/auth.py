from fastapi import APIRouter, Request, status

from app.api.dependencies.database import SessionDependency
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.common import ApiResponse
from app.schemas.user import UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=ApiResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: SessionDependency,
) -> ApiResponse[UserResponse]:
    user = await AuthService(session).register(payload)
    return ApiResponse(
        data=UserResponse.model_validate(user),
        request_id=request.state.request_id,
    )


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    payload: LoginRequest,
    request: Request,
    session: SessionDependency,
) -> ApiResponse[TokenResponse]:
    token = await AuthService(session).login(payload)
    return ApiResponse(data=token, request_id=request.state.request_id)
