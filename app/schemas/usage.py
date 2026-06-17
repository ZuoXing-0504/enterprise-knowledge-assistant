from pydantic import BaseModel


class ModelUsageBreakdown(BaseModel):
    model_name: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    average_latency_ms: float
    maximum_latency_ms: int
    estimated_cost_usd: float


class UsageSummaryResponse(BaseModel):
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    average_latency_ms: float
    maximum_latency_ms: int
    estimated_cost_usd: float
    by_model: list[ModelUsageBreakdown]
