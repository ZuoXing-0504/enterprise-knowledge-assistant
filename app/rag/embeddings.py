from collections.abc import Sequence
from typing import Protocol

import httpx
from anyio import sleep

from app.core.config import Settings
from app.rag.errors import EmbeddingServiceError


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.settings.openai_embedding_model:
            raise EmbeddingServiceError("Embedding model is not configured")

        embeddings: list[list[float]] = []
        async with httpx.AsyncClient(
            timeout=self.settings.model_request_timeout_seconds,
            transport=self.transport,
        ) as client:
            for start in range(0, len(texts), self.settings.embedding_batch_size):
                batch = list(texts[start : start + self.settings.embedding_batch_size])
                embeddings.extend(await self._embed_batch(client, batch))
        return embeddings

    async def _embed_batch(
        self,
        client: httpx.AsyncClient,
        texts: list[str],
    ) -> list[list[float]]:
        payload: dict[str, object] = {
            "model": self.settings.openai_embedding_model,
            "input": texts,
            "encoding_format": "float",
        }
        if self.settings.openai_embedding_send_dimensions:
            payload["dimensions"] = self.settings.embedding_dimension

        headers = {"Content-Type": "application/json"}
        if self.settings.openai_api_key is not None:
            api_key = self.settings.openai_api_key.get_secret_value()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        try:
            response: httpx.Response | None = None
            for attempt in range(self.settings.model_max_retries + 1):
                try:
                    response = await client.post(
                        f"{self.settings.openai_base_url.rstrip('/')}/embeddings",
                        headers=headers,
                        json=payload,
                    )
                    if response.status_code >= 400:
                        retryable = response.status_code == 429 or response.status_code >= 500
                        raise EmbeddingServiceError(
                            f"Embedding service returned HTTP {response.status_code}",
                            retryable=retryable,
                        )
                    break
                except (httpx.HTTPError, EmbeddingServiceError) as exc:
                    error = self._normalize_error(exc)
                    if not error.retryable or attempt >= self.settings.model_max_retries:
                        raise error from exc
                    await sleep(self.settings.model_retry_base_seconds * (2**attempt))
        except EmbeddingServiceError:
            raise

        if response is None:
            raise EmbeddingServiceError(
                "Embedding service is unavailable",
                retryable=True,
            )

        try:
            response_data = response.json()["data"]
            ordered = sorted(response_data, key=lambda item: item["index"])
            embeddings = [[float(value) for value in item["embedding"]] for item in ordered]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingServiceError("Embedding service returned an invalid response") from exc

        if len(embeddings) != len(texts):
            raise EmbeddingServiceError("Embedding service returned an unexpected item count")
        if any(len(embedding) != self.settings.embedding_dimension for embedding in embeddings):
            raise EmbeddingServiceError("Embedding dimension does not match EMBEDDING_DIMENSION")
        return embeddings

    @staticmethod
    def _normalize_error(
        exc: httpx.HTTPError | EmbeddingServiceError,
    ) -> EmbeddingServiceError:
        if isinstance(exc, EmbeddingServiceError):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return EmbeddingServiceError(
                "Embedding service timed out",
                retryable=True,
            )
        return EmbeddingServiceError(
            "Embedding service is unavailable",
            retryable=True,
        )
