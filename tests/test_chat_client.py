import json

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.rag.chat import OpenAICompatibleChatClient
from app.rag.errors import ChatServiceError


async def test_chat_client_sends_messages_and_reads_usage() -> None:
    captured_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "model": "compatible-chat-model",
                "choices": [{"message": {"role": "assistant", "content": "Answer [来源1]"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                },
            },
        )

    settings = get_settings()
    settings.openai_base_url = "https://models.example.test/v1"
    settings.openai_api_key = SecretStr("test-key")
    settings.openai_chat_model = "compatible-chat-model"
    client = OpenAICompatibleChatClient(settings, httpx.MockTransport(handler))

    result = await client.complete(
        [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "question"},
        ]
    )

    assert captured_payload["model"] == "compatible-chat-model"
    assert captured_payload["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]
    assert result.content == "Answer [来源1]"
    assert result.total_tokens == 14


async def test_chat_client_exposes_timeout_kind() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow model", request=request)

    settings = get_settings()
    settings.openai_chat_model = "compatible-chat-model"
    settings.model_max_retries = 0
    client = OpenAICompatibleChatClient(settings, httpx.MockTransport(handler))

    with pytest.raises(ChatServiceError) as exc_info:
        await client.complete([{"role": "user", "content": "question"}])

    assert exc_info.value.kind == "timeout"
    assert exc_info.value.retryable is True


async def test_chat_client_retries_rate_limit_before_success() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(
            200,
            json={
                "model": "compatible-chat-model",
                "choices": [{"message": {"content": "Recovered [来源1]"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    settings = get_settings()
    settings.openai_chat_model = "compatible-chat-model"
    settings.model_max_retries = 1
    settings.model_retry_base_seconds = 0
    client = OpenAICompatibleChatClient(settings, httpx.MockTransport(handler))

    result = await client.complete([{"role": "user", "content": "question"}])

    assert attempts == 2
    assert result.content == "Recovered [来源1]"


async def test_chat_stream_retries_before_first_token() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        body = (
            'data: {"model":"compatible-chat-model","choices":'
            '[{"delta":{"content":"Hello "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"[来源1]"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":3,'
            '"completion_tokens":2,"total_tokens":5}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            text=body,
            headers={"Content-Type": "text/event-stream"},
        )

    settings = get_settings()
    settings.openai_chat_model = "compatible-chat-model"
    settings.model_max_retries = 1
    settings.model_retry_base_seconds = 0
    client = OpenAICompatibleChatClient(settings, httpx.MockTransport(handler))

    chunks = [chunk async for chunk in client.stream([{"role": "user", "content": "question"}])]

    assert attempts == 2
    assert "".join(chunk.content for chunk in chunks if not chunk.done) == "Hello [来源1]"
    assert chunks[-1].done is True
    assert chunks[-1].total_tokens == 5
