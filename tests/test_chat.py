from collections.abc import AsyncIterator, Sequence
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.conversation import Conversation, Message, ModelUsage
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.rag.errors import ChatServiceError
from app.rag.types import ChatCompletionResult, ChatMessage, ChatStreamChunk
from tests.fakes import InMemoryRedis
from tests.helpers import create_authenticated_user, create_knowledge_base


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.call_count += 1
        return [[1.0, 0.0, 0.0] for _ in texts]


async def test_chat_rejects_empty_question(client: AsyncClient) -> None:
    _, headers = await create_authenticated_user(client, email="empty-question@example.com")
    knowledge_base = await create_knowledge_base(client, headers)

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": "   "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


class FakeChatProvider:
    def __init__(self, answer: str = "退款期限是七天 [来源1]") -> None:
        self.answer = answer
        self.messages: list[ChatMessage] = []
        self.call_count = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatCompletionResult:
        self.call_count += 1
        self.messages = list(messages)
        return ChatCompletionResult(
            content=self.answer,
            model_name="test-chat-model",
            prompt_tokens=20,
            completion_tokens=8,
            total_tokens=28,
            latency_ms=12,
        )

    async def stream(
        self,
        messages: Sequence[ChatMessage],
    ) -> AsyncIterator[ChatStreamChunk]:
        self.call_count += 1
        self.messages = list(messages)
        midpoint = len(self.answer) // 2
        yield ChatStreamChunk(content=self.answer[:midpoint])
        yield ChatStreamChunk(content=self.answer[midpoint:])
        yield ChatStreamChunk(
            model_name="test-chat-model",
            prompt_tokens=20,
            completion_tokens=8,
            total_tokens=28,
            latency_ms=12,
            done=True,
        )


class TimeoutChatProvider:
    async def complete(self, messages: Sequence[ChatMessage]) -> ChatCompletionResult:
        raise ChatServiceError("timed out", kind="timeout", retryable=True)

    async def stream(
        self,
        messages: Sequence[ChatMessage],
    ) -> AsyncIterator[ChatStreamChunk]:
        yield ChatStreamChunk(content="partial")
        raise ChatServiceError("timed out", kind="timeout", retryable=True)


async def create_completed_document(
    knowledge_base_id: str,
    *,
    content: str = "退款申请应在购买后七天内提交。",
) -> Document:
    async with async_session_factory() as session:
        document = Document(
            knowledge_base_id=UUID(knowledge_base_id),
            original_filename="refund-policy.md",
            storage_path=f"{knowledge_base_id}.md",
            content_type="text/markdown",
            file_size=len(content.encode()),
            status=DocumentStatus.COMPLETED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=0,
                content=content,
                source_paragraph=3,
                embedding=[1.0, 0.0, 0.0],
            )
        )
        await session.commit()
        await session.refresh(document)
        return document


def install_model_fakes(
    monkeypatch: pytest.MonkeyPatch,
    chat_provider: FakeChatProvider | TimeoutChatProvider,
) -> FakeEmbeddingProvider:
    embedding_provider = FakeEmbeddingProvider()
    monkeypatch.setattr(
        "app.services.chat.OpenAICompatibleEmbeddingClient",
        lambda settings: embedding_provider,
    )
    monkeypatch.setattr(
        "app.services.chat.OpenAICompatibleChatClient",
        lambda settings: chat_provider,
    )
    return embedding_provider


async def test_chat_returns_citations_and_persists_exchange(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, headers = await create_authenticated_user(client, email="chat@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    document = await create_completed_document(str(knowledge_base["id"]))
    chat_provider = FakeChatProvider()
    install_model_fakes(monkeypatch, chat_provider)
    question = "退款期限是什么？"

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": question},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer"] == "退款期限是七天 [来源1]"
    assert data["sources"] == [
        {
            "reference": "[来源1]",
            "document_id": str(document.id),
            "document_name": "refund-policy.md",
            "page_number": None,
            "paragraph_number": 3,
            "chunk_index": 0,
            "excerpt": "退款申请应在购买后七天内提交。",
            "similarity": 1.0,
        }
    ]
    assert data["usage"]["total_tokens"] == 28
    assert [message["role"] for message in chat_provider.messages] == [
        "system",
        "user",
        "user",
    ]
    assert question not in chat_provider.messages[0]["content"]
    assert chat_provider.messages[-1]["content"] == question
    assert "不可信参考数据" in chat_provider.messages[1]["content"]

    conversations = await client.get("/api/v1/conversations", headers=headers)
    messages = await client.get(
        f"/api/v1/conversations/{data['conversation_id']}/messages",
        headers=headers,
    )
    assert conversations.json()["data"]["pagination"]["total"] == 1
    assert messages.json()["data"]["pagination"]["total"] == 2
    assert [item["role"] for item in messages.json()["data"]["items"]] == [
        "user",
        "assistant",
    ]

    async with async_session_factory() as session:
        usage = (await session.execute(select(ModelUsage))).scalar_one()
        assert usage.model_name == "test-chat-model"
        assert usage.total_tokens == 28


async def test_chat_without_relevant_chunks_returns_unknown_without_model_call(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, headers = await create_authenticated_user(client, email="unknown@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    chat_provider = FakeChatProvider()
    install_model_fakes(monkeypatch, chat_provider)

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": "不存在的信息是什么？"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer"] == "根据当前知识库无法确定"
    assert data["sources"] == []
    assert data["usage"]["model_name"] is None
    assert chat_provider.call_count == 0
    async with async_session_factory() as session:
        usage_count = await session.scalar(select(func.count()).select_from(ModelUsage))
        assert usage_count == 0


async def test_uncited_model_answer_is_not_accepted(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, headers = await create_authenticated_user(client, email="uncited@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    await create_completed_document(str(knowledge_base["id"]))
    install_model_fakes(monkeypatch, FakeChatProvider("退款期限是七天"))

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": "退款期限是什么？"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["answer"] == "根据当前知识库无法确定"
    assert response.json()["data"]["sources"] == []


async def test_model_timeout_does_not_persist_partial_conversation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, headers = await create_authenticated_user(client, email="timeout@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    await create_completed_document(str(knowledge_base["id"]))
    install_model_fakes(monkeypatch, TimeoutChatProvider())

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": "退款期限是什么？"},
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "model_timeout"
    async with async_session_factory() as session:
        conversation_count = await session.scalar(select(func.count()).select_from(Conversation))
        message_count = await session.scalar(select(func.count()).select_from(Message))
        assert conversation_count == 0
        assert message_count == 0


async def test_conversation_access_is_scoped_to_owner(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, owner_headers = await create_authenticated_user(client, email="chat-owner@example.com")
    _, other_headers = await create_authenticated_user(client, email="chat-other@example.com")
    knowledge_base = await create_knowledge_base(client, owner_headers)
    await create_completed_document(str(knowledge_base["id"]))
    install_model_fakes(monkeypatch, FakeChatProvider())
    chat_response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=owner_headers,
        json={"question": "退款期限是什么？"},
    )
    conversation_id = chat_response.json()["data"]["conversation_id"]

    list_response = await client.get("/api/v1/conversations", headers=other_headers)
    messages_response = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=other_headers,
    )

    assert list_response.json()["data"]["pagination"]["total"] == 0
    assert messages_response.status_code == 404
    assert messages_response.json()["error"]["code"] == "conversation_not_found"


async def test_stream_chat_emits_sse_and_persists_only_completed_answer(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: InMemoryRedis,
) -> None:
    _, headers = await create_authenticated_user(client, email="stream@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    await create_completed_document(str(knowledge_base["id"]))
    install_model_fakes(monkeypatch, FakeChatProvider())

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat/stream",
        headers=headers,
        json={"question": "退款期限是什么？"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: metadata" in response.text
    assert response.text.count("event: token") == 2
    assert "event: done" in response.text
    async with async_session_factory() as session:
        roles = list(
            (await session.execute(select(Message.role).order_by(Message.created_at)))
            .scalars()
            .all()
        )
        assert roles == ["user", "assistant"]


async def test_stream_failure_emits_error_without_partial_persistence(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: InMemoryRedis,
) -> None:
    _, headers = await create_authenticated_user(client, email="stream-failure@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    await create_completed_document(str(knowledge_base["id"]))
    install_model_fakes(monkeypatch, TimeoutChatProvider())

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat/stream",
        headers=headers,
        json={"question": "退款期限是什么？"},
    )

    assert response.status_code == 200
    assert "event: token" in response.text
    assert "event: error" in response.text
    assert '"code":"model_timeout"' in response.text
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Message)) == 0
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 0


async def test_chat_rate_limit_uses_user_scoped_redis_counter(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: InMemoryRedis,
) -> None:
    settings = get_settings()
    settings.chat_rate_limit_requests = 1
    settings.chat_rate_limit_window_seconds = 30
    _, headers = await create_authenticated_user(client, email="limited@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    install_model_fakes(monkeypatch, FakeChatProvider())

    first = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": "first question"},
    )
    second = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": "second question"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(second.headers["Retry-After"]) > 0


async def test_embedding_cache_uses_hash_key_and_avoids_duplicate_model_calls(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: InMemoryRedis,
) -> None:
    _, headers = await create_authenticated_user(client, email="cache@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    question = "private repeated question"
    embedding_provider = install_model_fakes(monkeypatch, FakeChatProvider())

    for _ in range(2):
        response = await client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
            headers=headers,
            json={"question": question},
        )
        assert response.status_code == 200

    assert embedding_provider.call_count == 1
    assert any(key.startswith("embedding-cache:") for key in fake_redis.values)
    assert all(question not in key for key in fake_redis.values)


async def test_usage_summary_reports_cost_latency_and_user_isolation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.model_input_cost_per_1m_tokens = 1.0
    settings.model_output_cost_per_1m_tokens = 2.0
    _, headers = await create_authenticated_user(client, email="usage@example.com")
    _, other_headers = await create_authenticated_user(client, email="usage-other@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    await create_completed_document(str(knowledge_base["id"]))
    install_model_fakes(monkeypatch, FakeChatProvider())
    await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/chat",
        headers=headers,
        json={"question": "退款期限是什么？"},
    )

    summary = await client.get("/api/v1/usage/summary", headers=headers)
    other_summary = await client.get("/api/v1/usage/summary", headers=other_headers)

    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["request_count"] == 1
    assert data["total_tokens"] == 28
    assert data["average_latency_ms"] == 12
    assert data["estimated_cost_usd"] == 0.000036
    assert data["by_model"][0]["model_name"] == "test-chat-model"
    assert other_summary.json()["data"]["request_count"] == 0
