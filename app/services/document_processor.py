from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.document import Document, DocumentStatus
from app.rag.chunking import split_sections
from app.rag.embeddings import EmbeddingProvider
from app.rag.errors import DocumentProcessingError
from app.rag.parsers import parse_document
from app.rag.types import TextChunk
from app.repositories.document import DocumentRepository
from app.services.file_storage import FileStorage


class DocumentProcessor:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        settings: Settings,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.settings = settings
        self.documents = DocumentRepository(session)
        self.storage = FileStorage(settings)

    async def run(self, document_id: UUID, task_id: str) -> bool:
        document = await self._claim(document_id, task_id)
        if document is None:
            return False

        try:
            path = self.storage.resolve(document.storage_path)
            sections = await to_thread.run_sync(parse_document, path)
            chunks = split_sections(
                sections,
                chunk_size=self.settings.chunk_size,
                chunk_overlap=self.settings.chunk_overlap,
            )
            if not chunks:
                raise DocumentProcessingError("Document contains no extractable text")
            embeddings = await self.embedding_provider.embed([chunk.content for chunk in chunks])
            await self._complete(document_id, task_id, chunks, embeddings)
        except Exception as exc:
            error = self._normalize_error(exc)
            await self._mark_failed(document_id, task_id, str(error))
            raise error from exc
        return True

    async def _claim(self, document_id: UUID, task_id: str) -> Document | None:
        document = await self.documents.get_for_update(document_id)
        if document is None or document.status == DocumentStatus.COMPLETED.value:
            await self.session.rollback()
            return None
        if (
            document.status == DocumentStatus.PROCESSING.value
            and document.celery_task_id != task_id
        ):
            await self.session.rollback()
            return None

        document.status = DocumentStatus.PROCESSING.value
        document.celery_task_id = task_id
        document.error_message = None
        await self.session.commit()
        return document

    async def _complete(
        self,
        document_id: UUID,
        task_id: str,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> None:
        document = await self.documents.get_for_update(document_id)
        if document is None or document.celery_task_id != task_id:
            await self.session.rollback()
            return
        await self.documents.replace_chunks(document, chunks, embeddings)
        await self.session.commit()

    async def _mark_failed(self, document_id: UUID, task_id: str, message: str) -> None:
        await self.session.rollback()
        document = await self.documents.get_for_update(document_id)
        if document is None or document.celery_task_id != task_id:
            await self.session.rollback()
            return
        document.status = DocumentStatus.FAILED.value
        document.error_message = message[:1000]
        await self.session.commit()

    @staticmethod
    def _normalize_error(exc: Exception) -> DocumentProcessingError:
        if isinstance(exc, DocumentProcessingError):
            return exc
        if isinstance(exc, FileNotFoundError):
            return DocumentProcessingError("Uploaded file is no longer available")
        return DocumentProcessingError("Document processing failed")
