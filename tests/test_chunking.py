import pytest

from app.rag.chunking import split_sections
from app.rag.types import ParsedSection


def test_split_sections_preserves_source_and_overlap() -> None:
    text = " ".join(f"word-{index:02d}" for index in range(40))

    chunks = split_sections(
        [ParsedSection(text=text, page_number=3)],
        chunk_size=100,
        chunk_overlap=20,
    )

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page_number == 3 for chunk in chunks)
    assert all(chunk.paragraph_number is None for chunk in chunks)
    assert all(len(chunk.content) <= 100 for chunk in chunks)
    assert set(chunks[0].content.split()) & set(chunks[1].content.split())


def test_split_sections_keeps_paragraph_boundaries() -> None:
    chunks = split_sections(
        [
            ParsedSection(text="First paragraph", paragraph_number=1),
            ParsedSection(text="Second paragraph", paragraph_number=2),
        ],
        chunk_size=100,
        chunk_overlap=10,
    )

    assert [(chunk.content, chunk.paragraph_number) for chunk in chunks] == [
        ("First paragraph", 1),
        ("Second paragraph", 2),
    ]


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [(0, 0), (100, -1), (100, 100), (100, 101)],
)
def test_split_sections_rejects_invalid_configuration(
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    with pytest.raises(ValueError):
        split_sections(
            [ParsedSection(text="content")],
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
