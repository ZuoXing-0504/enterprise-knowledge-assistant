import asyncio
import logging
from uuid import UUID

from celery import Task
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.rag.embeddings import OpenAICompatibleEmbeddingClient
from app.rag.errors import DocumentProcessingError
from app.services.document_processor import DocumentProcessor
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.documents.process_document",
    max_retries=3,
)
def process_document(self: Task, document_id: str) -> dict[str, str]:
    task_id = str(self.request.id)
    try:
        processed = asyncio.run(_process_document(UUID(document_id), task_id))
    except DocumentProcessingError as exc:
        logger.warning(
            "document_processing_failed document_id=%s retryable=%s",
            document_id,
            exc.retryable,
        )
        if exc.retryable:
            countdown = min(2 ** (self.request.retries + 1), 30)
            raise self.retry(exc=exc, countdown=countdown) from exc
        return {"status": "failed", "document_id": document_id}
    return {
        "status": "completed" if processed else "skipped",
        "document_id": document_id,
    }


async def _process_document(document_id: UUID, task_id: str) -> bool:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            processor = DocumentProcessor(
                session,
                OpenAICompatibleEmbeddingClient(settings),
                settings,
            )
            return await processor.run(document_id, task_id)
    finally:
        await engine.dispose()
