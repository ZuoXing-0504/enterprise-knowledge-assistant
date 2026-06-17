from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ParsedSection:
    text: str
    page_number: int | None = None
    paragraph_number: int | None = None


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    content: str
    page_number: int | None = None
    paragraph_number: int | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    document_id: UUID
    document_name: str
    chunk_index: int
    content: str
    page_number: int | None
    paragraph_number: int | None
    similarity: float


@dataclass(frozen=True, slots=True)
class ContextSource:
    number: int
    document_id: UUID
    document_name: str
    chunk_index: int
    page_number: int | None
    paragraph_number: int | None
    excerpt: str
    similarity: float

    @property
    def reference(self) -> str:
        return f"[来源{self.number}]"


@dataclass(frozen=True, slots=True)
class ContextBundle:
    text: str
    sources: list[ContextSource]


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ChatCompletionResult:
    content: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class ChatStreamChunk:
    content: str = ""
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    done: bool = False
