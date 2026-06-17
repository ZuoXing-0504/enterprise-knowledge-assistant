import re

from app.rag.types import ContextBundle, ContextSource, RetrievedChunk

CITATION_PATTERN = re.compile(r"\[来源(\d+)\]")


def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_chars: int,
    excerpt_chars: int,
) -> ContextBundle:
    blocks: list[str] = []
    sources: list[ContextSource] = []
    used_chars = 0

    for chunk in chunks:
        number = len(sources) + 1
        location = _format_location(chunk)
        header = f"[来源{number}]\n文档：{chunk.document_name}\n位置：{location}\n内容：\n"
        separator = "\n\n" if blocks else ""
        available = max_chars - used_chars - len(separator) - len(header)
        if available <= 0:
            break

        content = chunk.content[:available].strip()
        if not content:
            continue
        block = f"{separator}{header}{content}"
        blocks.append(block)
        used_chars += len(block)
        sources.append(
            ContextSource(
                number=number,
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                paragraph_number=chunk.paragraph_number,
                excerpt=chunk.content[:excerpt_chars].strip(),
                similarity=chunk.similarity,
            )
        )

    return ContextBundle(text="".join(blocks), sources=sources)


def select_cited_sources(
    answer: str,
    sources: list[ContextSource],
) -> list[ContextSource]:
    source_by_number = {source.number: source for source in sources}
    cited: list[ContextSource] = []
    seen: set[int] = set()
    for match in CITATION_PATTERN.finditer(answer):
        number = int(match.group(1))
        if number in seen or number not in source_by_number:
            continue
        seen.add(number)
        cited.append(source_by_number[number])
    return cited


def citations_are_valid(answer: str, sources: list[ContextSource]) -> bool:
    available_numbers = {source.number for source in sources}
    referenced_numbers = [int(match.group(1)) for match in CITATION_PATTERN.finditer(answer)]
    return bool(referenced_numbers) and all(
        number in available_numbers for number in referenced_numbers
    )


def _format_location(chunk: RetrievedChunk) -> str:
    if chunk.page_number is not None:
        return f"第 {chunk.page_number} 页"
    if chunk.paragraph_number is not None:
        return f"第 {chunk.paragraph_number} 段"
    return f"片段 {chunk.chunk_index + 1}"
