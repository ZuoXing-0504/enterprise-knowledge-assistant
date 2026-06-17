from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.schemas.common import ApiResponse
from app.schemas.health import HealthData

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=ApiResponse[HealthData])
async def health_check(request: Request) -> ApiResponse[HealthData]:
    settings = get_settings()
    return ApiResponse(
        data=HealthData(
            status="ok",
            environment=settings.app_env,
            version=settings.app_version,
        ),
        request_id=request.state.request_id,
    )
