import json
from collections.abc import AsyncIterator, Sequence
from time import perf_counter
from typing import Protocol

import httpx
from anyio import sleep

from app.core.config import Settings
from app.rag.errors import ChatServiceError
from app.rag.types import ChatCompletionResult, ChatMessage, ChatStreamChunk


class ChatProvider(Protocol):
    async def complete(self, messages: Sequence[ChatMessage]) -> ChatCompletionResult: ...

    def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[ChatStreamChunk]: ...


class OpenAICompatibleChatClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatCompletionResult:
        if not self.settings.openai_chat_model:
            raise ChatServiceError(
                "Chat model is not configured",
                kind="configuration",
            )

        headers = {"Content-Type": "application/json"}
        if self.settings.openai_api_key is not None:
            api_key = self.settings.openai_api_key.get_secret_value()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.settings.openai_chat_model,
            "messages": list(messages),
            "max_tokens": self.settings.openai_chat_max_tokens,
        }
        started_at = perf_counter()
        response: httpx.Response | None = None
        for attempt in range(self.settings.model_max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.model_request_timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = await client.post(
                        f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                self._raise_for_status(response, service_name="Chat")
                break
            except (httpx.HTTPError, ChatServiceError) as exc:
                error = self._normalize_error(exc, service_name="Chat")
                if not error.retryable or attempt >= self.settings.model_max_retries:
                    raise error from exc
                await sleep(self._retry_delay(attempt))

        if response is None:
            raise ChatServiceError(
                "Chat service is unavailable",
                kind="unavailable",
                retryable=True,
            )
        latency_ms = max(0, round((perf_counter() - started_at) * 1000))

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"].strip()
            model_name = str(body.get("model") or self.settings.openai_chat_model)
            usage = body.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
            completion_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
            total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise ChatServiceError(
                "Chat service returned an invalid response",
                kind="invalid_response",
            ) from exc
        if not content:
            raise ChatServiceError(
                "Chat service returned an empty response",
                kind="invalid_response",
            )

        return ChatCompletionResult(
            content=content,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: Sequence[ChatMessage],
    ) -> AsyncIterator[ChatStreamChunk]:
        if not self.settings.openai_chat_model:
            raise ChatServiceError(
                "Chat model is not configured",
                kind="configuration",
            )

        headers = {"Content-Type": "application/json"}
        if self.settings.openai_api_key is not None:
            api_key = self.settings.openai_api_key.get_secret_value()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": self.settings.openai_chat_model,
            "messages": list(messages),
            "max_tokens": self.settings.openai_chat_max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        started_at = perf_counter()
        for attempt in range(self.settings.model_max_retries + 1):
            emitted_content = False
            model_name = self.settings.openai_chat_model
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.model_request_timeout_seconds,
                    transport=self.transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as response:
                        self._raise_for_status(response, service_name="Chat")
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if not data or data == "[DONE]":
                                continue
                            try:
                                body = json.loads(data)
                                model_name = str(body.get("model") or model_name)
                                usage = body.get("usage") or {}
                                prompt_tokens = int(usage.get("prompt_tokens", prompt_tokens))
                                completion_tokens = int(
                                    usage.get("completion_tokens", completion_tokens)
                                )
                                total_tokens = int(
                                    usage.get(
                                        "total_tokens",
                                        prompt_tokens + completion_tokens,
                                    )
                                )
                                choices = body.get("choices") or []
                                content = (
                                    choices[0].get("delta", {}).get("content", "")
                                    if choices
                                    else ""
                                )
                            except (IndexError, TypeError, ValueError) as exc:
                                raise ChatServiceError(
                                    "Chat service returned an invalid stream",
                                    kind="invalid_response",
                                ) from exc
                            if content:
                                emitted_content = True
                                yield ChatStreamChunk(content=str(content))

                yield ChatStreamChunk(
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=max(0, round((perf_counter() - started_at) * 1000)),
                    done=True,
                )
                return
            except (httpx.HTTPError, ChatServiceError) as exc:
                error = self._normalize_error(exc, service_name="Chat")
                if (
                    emitted_content
                    or not error.retryable
                    or attempt >= self.settings.model_max_retries
                ):
                    raise error from exc
                await sleep(self._retry_delay(attempt))

    def _retry_delay(self, attempt: int) -> float:
        return self.settings.model_retry_base_seconds * (2**attempt)

    @staticmethod
    def _raise_for_status(
        response: httpx.Response,
        *,
        service_name: str,
    ) -> None:
        if response.status_code < 400:
            return
        kind = "rate_limit" if response.status_code == 429 else "unavailable"
        retryable = response.status_code == 429 or response.status_code >= 500
        raise ChatServiceError(
            f"{service_name} service returned HTTP {response.status_code}",
            kind=kind,
            retryable=retryable,
        )

    @staticmethod
    def _normalize_error(
        exc: httpx.HTTPError | ChatServiceError,
        *,
        service_name: str,
    ) -> ChatServiceError:
        if isinstance(exc, ChatServiceError):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return ChatServiceError(
                f"{service_name} service timed out",
                kind="timeout",
                retryable=True,
            )
        return ChatServiceError(
            f"{service_name} service is unavailable",
            kind="unavailable",
            retryable=True,
        )
