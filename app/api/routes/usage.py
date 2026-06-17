from fastapi import APIRouter, Request

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.database import SessionDependency
from app.schemas.common import ApiResponse
from app.schemas.usage import UsageSummaryResponse
from app.services.usage import UsageService

router = APIRouter(prefix="/usage", tags=["Usage"])


@router.get("/summary", response_model=ApiResponse[UsageSummaryResponse])
async def get_usage_summary(
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ApiResponse[UsageSummaryResponse]:
    summary = await UsageService(session).summary(current_user.id)
    return ApiResponse(data=summary, request_id=request.state.request_id)
