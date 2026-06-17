import logging
from math import ceil
from uuid import UUID

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models.knowledge_base import KnowledgeBase
from app.repositories.document import DocumentRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.schemas.common import PageResponse, PaginationMeta
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from app.services.file_storage import FileStorage

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.knowledge_bases = KnowledgeBaseRepository(session)
        self.documents = DocumentRepository(session)
        self.storage = FileStorage(get_settings())

    async def create(self, owner_id: UUID, payload: KnowledgeBaseCreate) -> KnowledgeBase:
        knowledge_base = await self.knowledge_bases.create(
            owner_id=owner_id,
            name=payload.name,
            description=payload.description,
        )
        await self.session.commit()
        return knowledge_base

    async def get(self, knowledge_base_id: UUID, owner_id: UUID) -> KnowledgeBase:
        return await self._get_owned_or_404(knowledge_base_id, owner_id)

    async def list(
        self,
        owner_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> PageResponse[KnowledgeBaseResponse]:
        items, total = await self.knowledge_bases.list_owned(
            owner_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return PageResponse(
            items=[KnowledgeBaseResponse.model_validate(item) for item in items],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total=total,
                pages=ceil(total / page_size) if total else 0,
            ),
        )

    async def update(
        self,
        knowledge_base_id: UUID,
        owner_id: UUID,
        payload: KnowledgeBaseUpdate,
    ) -> KnowledgeBase:
        knowledge_base = await self._get_owned_or_404(knowledge_base_id, owner_id)
        updated = await self.knowledge_bases.update(
            knowledge_base,
            payload.model_dump(exclude_unset=True),
        )
        await self.session.commit()
        return updated

    async def delete(self, knowledge_base_id: UUID, owner_id: UUID) -> None:
        knowledge_base = await self._get_owned_or_404(knowledge_base_id, owner_id)
        storage_paths = await self.documents.list_storage_paths_for_knowledge_base(
            knowledge_base_id
        )
        await self.knowledge_bases.delete(knowledge_base)
        await self.session.commit()
        try:
            await self.storage.delete_many(storage_paths)
        except OSError as exc:
            logger.warning(
                "knowledge_base_file_cleanup_failed knowledge_base_id=%s exception_type=%s",
                knowledge_base_id,
                type(exc).__name__,
            )

    async def _get_owned_or_404(
        self,
        knowledge_base_id: UUID,
        owner_id: UUID,
    ) -> KnowledgeBase:
        knowledge_base = await self.knowledge_bases.get_owned(knowledge_base_id, owner_id)
        if knowledge_base is None:
            raise AppError(
                code="knowledge_base_not_found",
                message="Knowledge base was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return knowledge_base
