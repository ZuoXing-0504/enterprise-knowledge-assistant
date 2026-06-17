from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message, MessageRole, ModelUsage


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        owner_id: UUID,
        knowledge_base_id: UUID,
        title: str,
    ) -> Conversation:
        conversation = Conversation(
            owner_id=owner_id,
            knowledge_base_id=knowledge_base_id,
            title=title,
        )
        self.session.add(conversation)
        await self.session.flush()
        await self.session.refresh(conversation)
        return conversation

    async def get_owned(
        self,
        conversation_id: UUID,
        owner_id: UUID,
    ) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_owned(
        self,
        owner_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[Conversation], int]:
        total = await self.session.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.owner_id == owner_id)
        )
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.owner_id == owner_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def add_message(
        self,
        conversation: Conversation,
        *,
        role: MessageRole,
        content: str,
        citations: list[dict[str, object]] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            role=role.value,
            content=content,
            citations=citations,
            created_at=datetime.now(UTC),
        )
        conversation.updated_at = datetime.now(UTC)
        self.session.add(message)
        await self.session.flush()
        await self.session.refresh(message)
        return message

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[Message], int]:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def add_usage(
        self,
        *,
        owner_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
    ) -> ModelUsage:
        usage = ModelUsage(
            owner_id=owner_id,
            conversation_id=conversation_id,
            message_id=message_id,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )
        self.session.add(usage)
        await self.session.flush()
        return usage

    async def summarize_usage(self, owner_id: UUID) -> list[tuple[object, ...]]:
        result = await self.session.execute(
            select(
                ModelUsage.model_name,
                func.count(ModelUsage.id),
                func.coalesce(func.sum(ModelUsage.prompt_tokens), 0),
                func.coalesce(func.sum(ModelUsage.completion_tokens), 0),
                func.coalesce(func.sum(ModelUsage.total_tokens), 0),
                func.coalesce(func.avg(ModelUsage.latency_ms), 0),
                func.coalesce(func.max(ModelUsage.latency_ms), 0),
            )
            .where(ModelUsage.owner_id == owner_id)
            .group_by(ModelUsage.model_name)
            .order_by(ModelUsage.model_name)
        )
        return list(result.all())
