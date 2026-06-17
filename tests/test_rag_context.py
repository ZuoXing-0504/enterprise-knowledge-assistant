from uuid import uuid4

from app.rag.context import build_context, citations_are_valid, select_cited_sources
from app.rag.types import RetrievedChunk


def test_context_builder_respects_budget_and_preserves_sources() -> None:
    chunks = [
        RetrievedChunk(
            document_id=uuid4(),
            document_name="handbook.pdf",
            chunk_index=0,
            content="A" * 800,
            page_number=2,
            paragraph_number=None,
            similarity=0.91,
        ),
        RetrievedChunk(
            document_id=uuid4(),
            document_name="policy.md",
            chunk_index=1,
            content="B" * 800,
            page_number=None,
            paragraph_number=4,
            similarity=0.84,
        ),
    ]

    context = build_context(chunks, max_chars=1000, excerpt_chars=80)

    assert len(context.text) <= 1000
    assert context.text.startswith("[来源1]")
    assert "文档：handbook.pdf" in context.text
    assert context.sources[0].reference == "[来源1]"
    assert len(context.sources[0].excerpt) == 80


def test_only_valid_referenced_sources_are_selected() -> None:
    chunk = RetrievedChunk(
        document_id=uuid4(),
        document_name="guide.txt",
        chunk_index=0,
        content="Supported fact",
        page_number=None,
        paragraph_number=1,
        similarity=0.9,
    )
    context = build_context([chunk], max_chars=1000, excerpt_chars=100)

    cited = select_cited_sources(
        "The fact is supported [来源1]. Duplicate [来源1], invalid [来源9].",
        context.sources,
    )

    assert [source.reference for source in cited] == ["[来源1]"]
    assert citations_are_valid("Supported [来源1]", context.sources) is True
    assert citations_are_valid("Mixed [来源1] [来源9]", context.sources) is False
