from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase


class KnowledgeBaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        owner_id: UUID,
        name: str,
        description: str | None,
    ) -> KnowledgeBase:
        knowledge_base = KnowledgeBase(
            owner_id=owner_id,
            name=name,
            description=description,
        )
        self.session.add(knowledge_base)
        await self.session.flush()
        await self.session.refresh(knowledge_base)
        return knowledge_base

    async def get_owned(self, knowledge_base_id: UUID, owner_id: UUID) -> KnowledgeBase | None:
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_owned(
        self,
        owner_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[KnowledgeBase], int]:
        filters = (KnowledgeBase.owner_id == owner_id,)
        total = await self.session.scalar(
            select(func.count()).select_from(KnowledgeBase).where(*filters)
        )
        result = await self.session.execute(
            select(KnowledgeBase)
            .where(*filters)
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def update(
        self,
        knowledge_base: KnowledgeBase,
        changes: dict[str, object],
    ) -> KnowledgeBase:
        for field, value in changes.items():
            setattr(knowledge_base, field, value)
        await self.session.flush()
        await self.session.refresh(knowledge_base)
        return knowledge_base

    async def delete(self, knowledge_base: KnowledgeBase) -> None:
        await self.session.delete(knowledge_base)
