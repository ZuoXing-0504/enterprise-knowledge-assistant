from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.conversation import MessageRole

Question = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ChatRequest(BaseModel):
    question: Question
    conversation_id: UUID | None = None


class CitationResponse(BaseModel):
    reference: str
    document_id: UUID
    document_name: str
    page_number: int | None
    paragraph_number: int | None
    chunk_index: int
    excerpt: str
    similarity: float


class ChatUsageResponse(BaseModel):
    model_name: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    sources: list[CitationResponse]
    usage: ChatUsageResponse


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    citations: list[CitationResponse] | None
    created_at: datetime
