from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.rag.types import TextChunk


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        knowledge_base_id: UUID,
        original_filename: str,
        storage_path: str,
        content_type: str,
        file_size: int,
    ) -> Document:
        document = Document(
            knowledge_base_id=knowledge_base_id,
            original_filename=original_filename,
            storage_path=storage_path,
            content_type=content_type,
            file_size=file_size,
        )
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def get_owned(self, document_id: UUID, owner_id: UUID) -> Document | None:
        result = await self.session.execute(
            select(Document)
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .where(Document.id == document_id, KnowledgeBase.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def list_owned(
        self,
        knowledge_base_id: UUID,
        owner_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[Document], int]:
        filters = (
            Document.knowledge_base_id == knowledge_base_id,
            KnowledgeBase.owner_id == owner_id,
        )
        base_query = select(Document).join(
            KnowledgeBase,
            KnowledgeBase.id == Document.knowledge_base_id,
        )
        total = await self.session.scalar(
            select(func.count())
            .select_from(Document)
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .where(*filters)
        )
        result = await self.session.execute(
            base_query.where(*filters)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get_for_update(self, document_id: UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def set_task_id(self, document: Document, task_id: str) -> None:
        document.celery_task_id = task_id
        await self.session.flush()

    async def mark_enqueue_failed(self, document: Document, message: str) -> None:
        document.status = DocumentStatus.FAILED.value
        document.error_message = message
        await self.session.flush()

    async def replace_chunks(
        self,
        document: Document,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> None:
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
        )
        self.session.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    source_page=chunk.page_number,
                    source_paragraph=chunk.paragraph_number,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]
        )
        document.status = DocumentStatus.COMPLETED.value
        document.error_message = None
        await self.session.flush()

    async def list_storage_paths_for_knowledge_base(
        self,
        knowledge_base_id: UUID,
    ) -> list[str]:
        result = await self.session.execute(
            select(Document.storage_path).where(Document.knowledge_base_id == knowledge_base_id)
        )
        return list(result.scalars().all())

    async def delete(self, document: Document) -> None:
        await self.session.delete(document)
