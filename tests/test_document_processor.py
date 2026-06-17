from collections.abc import Sequence

import pytest
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.rag.errors import DocumentProcessingError, EmbeddingServiceError
from app.services.document_processor import DocumentProcessor


class FakeEmbeddingProvider:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(index), 0.5, 1.0] for index, _ in enumerate(texts)]


class FailingEmbeddingProvider:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingServiceError("Embedding service timed out", retryable=True)


async def create_document_record(
    *,
    content: str,
    filename: str = "document.txt",
) -> tuple[Document, Settings]:
    settings = get_settings()
    path = settings.upload_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    async with async_session_factory() as session:
        user = User(email="processor@example.com", password_hash="hash")
        session.add(user)
        await session.flush()
        knowledge_base = KnowledgeBase(owner_id=user.id, name="Processor KB")
        session.add(knowledge_base)
        await session.flush()
        document = Document(
            knowledge_base_id=knowledge_base.id,
            original_filename=filename,
            storage_path=filename,
            content_type="text/plain",
            file_size=path.stat().st_size,
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        return document, settings


async def test_document_processor_writes_chunks_and_is_idempotent() -> None:
    document, settings = await create_document_record(
        content=("First paragraph has enough text for processing. " * 8)
        + "\n\n"
        + ("Second paragraph is also retained with its source. " * 8)
    )

    async with async_session_factory() as session:
        processor = DocumentProcessor(session, FakeEmbeddingProvider(), settings)
        processed = await processor.run(document.id, "task-one")
        repeated = await processor.run(document.id, "task-two")

        stored_document = await session.get(Document, document.id)
        chunks = list(
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document.id)
                    .order_by(DocumentChunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )

    assert processed is True
    assert repeated is False
    assert stored_document is not None
    assert stored_document.status == DocumentStatus.COMPLETED.value
    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.source_paragraph for chunk in chunks} == {1, 2}
    assert all(len(chunk.embedding) == 3 for chunk in chunks)


async def test_document_processor_records_empty_document_failure() -> None:
    document, settings = await create_document_record(content=" \n\n ", filename="empty.txt")

    async with async_session_factory() as session:
        processor = DocumentProcessor(session, FakeEmbeddingProvider(), settings)
        with pytest.raises(DocumentProcessingError, match="no extractable text"):
            await processor.run(document.id, "empty-task")

        stored_document = await session.get(Document, document.id)
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
        )

    assert stored_document is not None
    assert stored_document.status == DocumentStatus.FAILED.value
    assert stored_document.error_message == "Document contains no extractable text"
    assert chunk_count == 0


async def test_document_processor_records_embedding_failure() -> None:
    document, settings = await create_document_record(
        content="A document with extractable text.",
        filename="embedding-failure.txt",
    )

    async with async_session_factory() as session:
        processor = DocumentProcessor(session, FailingEmbeddingProvider(), settings)
        with pytest.raises(EmbeddingServiceError, match="timed out") as exc_info:
            await processor.run(document.id, "embedding-task")

        stored_document = await session.get(Document, document.id)
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
        )

    assert exc_info.value.retryable is True
    assert stored_document is not None
    assert stored_document.status == DocumentStatus.FAILED.value
    assert stored_document.error_message == "Embedding service timed out"
    assert chunk_count == 0
