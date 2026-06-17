import math
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.rag.types import RetrievedChunk


class RetrievalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        knowledge_base_id: UUID,
        query_embedding: list[float],
        *,
        limit: int,
    ) -> list[RetrievedChunk]:
        if self.session.get_bind().dialect.name == "postgresql":
            return await self._search_postgresql(
                knowledge_base_id,
                query_embedding,
                limit=limit,
            )
        return await self._search_in_memory(
            knowledge_base_id,
            query_embedding,
            limit=limit,
        )

    async def _search_postgresql(
        self,
        knowledge_base_id: UUID,
        query_embedding: list[float],
        *,
        limit: int,
    ) -> list[RetrievedChunk]:
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        result = await self.session.execute(
            select(
                DocumentChunk,
                Document.id.label("document_id"),
                Document.original_filename,
                distance.label("distance"),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.status == DocumentStatus.COMPLETED.value,
            )
            .order_by(distance)
            .limit(limit)
        )
        return [
            self._to_retrieved_chunk(
                chunk,
                document_id,
                original_filename,
                1.0 - float(distance_value),
            )
            for chunk, document_id, original_filename, distance_value in result.all()
        ]

    async def _search_in_memory(
        self,
        knowledge_base_id: UUID,
        query_embedding: list[float],
        *,
        limit: int,
    ) -> list[RetrievedChunk]:
        result = await self.session.execute(
            select(DocumentChunk, Document.id, Document.original_filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.status == DocumentStatus.COMPLETED.value,
            )
        )
        ranked = [
            self._to_retrieved_chunk(
                chunk,
                document_id,
                original_filename,
                _cosine_similarity(query_embedding, chunk.embedding),
            )
            for chunk, document_id, original_filename in result.all()
        ]
        ranked.sort(key=lambda item: item.similarity, reverse=True)
        return ranked[:limit]

    @staticmethod
    def _to_retrieved_chunk(
        chunk: DocumentChunk,
        document_id: UUID,
        original_filename: str,
        similarity: float,
    ) -> RetrievedChunk:
        return RetrievedChunk(
            document_id=document_id,
            document_name=original_filename,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            page_number=chunk.source_page,
            paragraph_number=chunk.source_paragraph,
            similarity=max(-1.0, min(1.0, similarity)),
        )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return -1.0
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    return dot_product / (left_norm * right_norm)
