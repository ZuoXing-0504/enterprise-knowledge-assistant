from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.repositories.conversation import ConversationRepository
from app.schemas.usage import ModelUsageBreakdown, UsageSummaryResponse


class UsageService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.repository = ConversationRepository(session)
        self.settings = settings or get_settings()

    async def summary(self, owner_id: UUID) -> UsageSummaryResponse:
        rows = await self.repository.summarize_usage(owner_id)
        by_model = [
            ModelUsageBreakdown(
                model_name=str(row[0]),
                request_count=int(row[1]),
                prompt_tokens=int(row[2]),
                completion_tokens=int(row[3]),
                total_tokens=int(row[4]),
                average_latency_ms=round(float(row[5]), 2),
                maximum_latency_ms=int(row[6]),
                estimated_cost_usd=self._estimated_cost(int(row[2]), int(row[3])),
            )
            for row in rows
        ]
        request_count = sum(item.request_count for item in by_model)
        weighted_latency = sum(item.average_latency_ms * item.request_count for item in by_model)
        return UsageSummaryResponse(
            request_count=request_count,
            prompt_tokens=sum(item.prompt_tokens for item in by_model),
            completion_tokens=sum(item.completion_tokens for item in by_model),
            total_tokens=sum(item.total_tokens for item in by_model),
            average_latency_ms=(round(weighted_latency / request_count, 2) if request_count else 0),
            maximum_latency_ms=max(
                (item.maximum_latency_ms for item in by_model),
                default=0,
            ),
            estimated_cost_usd=round(
                sum(item.estimated_cost_usd for item in by_model),
                6,
            ),
            by_model=by_model,
        )

    def _estimated_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        cost = (
            prompt_tokens * self.settings.model_input_cost_per_1m_tokens
            + completion_tokens * self.settings.model_output_cost_per_1m_tokens
        ) / 1_000_000
        return round(cost, 6)
