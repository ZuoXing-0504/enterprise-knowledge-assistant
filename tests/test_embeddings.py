import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.rag.embeddings import OpenAICompatibleEmbeddingClient
from app.rag.errors import EmbeddingServiceError


async def test_embedding_client_batches_and_orders_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = request.read()
        assert request.headers["Authorization"] == "Bearer test-key"
        assert b'"encoding_format":"float"' in payload
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0, 1, 0]},
                    {"index": 0, "embedding": [1, 0, 0]},
                ]
            },
        )

    settings = get_settings()
    settings.openai_base_url = "https://models.example.test/v1"
    settings.openai_api_key = SecretStr("test-key")
    settings.embedding_batch_size = 2
    client = OpenAICompatibleEmbeddingClient(settings, httpx.MockTransport(handler))

    embeddings = await client.embed(["first", "second"])

    assert embeddings == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert len(requests) == 1
    assert requests[0].url == "https://models.example.test/v1/embeddings"


async def test_embedding_client_marks_rate_limit_as_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    settings = get_settings()
    settings.model_max_retries = 0
    client = OpenAICompatibleEmbeddingClient(
        settings,
        httpx.MockTransport(handler),
    )

    with pytest.raises(EmbeddingServiceError) as exc_info:
        await client.embed(["content"])

    assert exc_info.value.retryable is True
    assert str(exc_info.value) == "Embedding service returned HTTP 429"


async def test_embedding_client_rejects_wrong_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1, 0]}]},
        )

    client = OpenAICompatibleEmbeddingClient(
        get_settings(),
        httpx.MockTransport(handler),
    )

    with pytest.raises(EmbeddingServiceError, match="dimension"):
        await client.embed(["content"])


async def test_embedding_client_retries_service_error_before_success() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1, 0, 0]}]},
        )

    settings = get_settings()
    settings.model_max_retries = 1
    settings.model_retry_base_seconds = 0
    client = OpenAICompatibleEmbeddingClient(
        settings,
        httpx.MockTransport(handler),
    )

    embeddings = await client.embed(["content"])

    assert attempts == 2
    assert embeddings == [[1.0, 0.0, 0.0]]
