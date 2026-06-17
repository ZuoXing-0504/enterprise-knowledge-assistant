import logging
from math import ceil
from uuid import UUID

from anyio import to_thread
from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models.document import Document
from app.repositories.document import DocumentRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.schemas.common import PageResponse, PaginationMeta
from app.schemas.document import DocumentResponse
from app.services.file_storage import FileStorage
from app.tasks.documents import process_document

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.documents = DocumentRepository(session)
        self.knowledge_bases = KnowledgeBaseRepository(session)
        self.storage = FileStorage(get_settings())

    async def upload(
        self,
        knowledge_base_id: UUID,
        owner_id: UUID,
        upload: UploadFile,
    ) -> Document:
        if await self.knowledge_bases.get_owned(knowledge_base_id, owner_id) is None:
            raise AppError(
                code="knowledge_base_not_found",
                message="Knowledge base was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        stored_file = await self.storage.save_upload(upload)
        try:
            document = await self.documents.create(
                knowledge_base_id=knowledge_base_id,
                original_filename=stored_file.original_filename,
                storage_path=stored_file.storage_path,
                content_type=stored_file.content_type,
                file_size=stored_file.file_size,
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            await self.storage.delete(stored_file.storage_path)
            raise

        try:
            result = await to_thread.run_sync(process_document.delay, str(document.id))
            await self.documents.set_task_id(document, str(result.id))
            await self.session.commit()
            await self.session.refresh(document)
        except Exception as exc:
            logger.error(
                "document_task_enqueue_failed document_id=%s exception_type=%s",
                document.id,
                type(exc).__name__,
            )
            await self.session.rollback()
            document = await self.documents.get_owned(document.id, owner_id)
            if document is not None:
                await self.documents.mark_enqueue_failed(
                    document,
                    "Document processing task could not be queued",
                )
                await self.session.commit()
            raise AppError(
                code="document_task_unavailable",
                message="Document was uploaded but processing could not be started",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        return document

    async def get(self, document_id: UUID, owner_id: UUID) -> Document:
        return await self._get_owned_or_404(document_id, owner_id)

    async def list(
        self,
        knowledge_base_id: UUID,
        owner_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> PageResponse[DocumentResponse]:
        if await self.knowledge_bases.get_owned(knowledge_base_id, owner_id) is None:
            raise AppError(
                code="knowledge_base_not_found",
                message="Knowledge base was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        documents, total = await self.documents.list_owned(
            knowledge_base_id,
            owner_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return PageResponse(
            items=[DocumentResponse.model_validate(document) for document in documents],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total=total,
                pages=ceil(total / page_size) if total else 0,
            ),
        )

    async def delete(self, document_id: UUID, owner_id: UUID) -> None:
        document = await self._get_owned_or_404(document_id, owner_id)
        storage_path = document.storage_path
        await self.documents.delete(document)
        await self.session.commit()
        try:
            await self.storage.delete(storage_path)
        except OSError as exc:
            logger.warning(
                "document_file_cleanup_failed document_id=%s exception_type=%s",
                document_id,
                type(exc).__name__,
            )

    async def _get_owned_or_404(self, document_id: UUID, owner_id: UUID) -> Document:
        document = await self.documents.get_owned(document_id, owner_id)
        if document is None:
            raise AppError(
                code="document_not_found",
                message="Document was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return document
