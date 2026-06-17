from app.rag.types import ParsedSection, TextChunk


def split_sections(
    sections: list[ParsedSection],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be between zero and chunk_size")

    chunks: list[TextChunk] = []
    for section in sections:
        for content in _split_text(section.text, chunk_size, chunk_overlap):
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    content=content,
                    page_number=section.page_number,
                    paragraph_number=section.paragraph_number,
                )
            )
    return chunks


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    stripped_text = text.strip()
    if not stripped_text:
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(stripped_text)
    minimum_split = max(1, int(chunk_size * 0.6))

    while start < text_length:
        maximum_end = min(start + chunk_size, text_length)
        end = maximum_end
        if maximum_end < text_length:
            split_at = _find_split_position(
                stripped_text,
                start + minimum_split,
                maximum_end,
            )
            if split_at is not None:
                end = split_at

        content = stripped_text[start:end].strip()
        if content:
            chunks.append(content)
        if end >= text_length:
            break

        next_start = max(end - chunk_overlap, start + 1)
        while next_start < end and stripped_text[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks


def _find_split_position(text: str, minimum: int, maximum: int) -> int | None:
    for index in range(maximum, minimum - 1, -1):
        if text[index - 1].isspace():
            return index
    return None
