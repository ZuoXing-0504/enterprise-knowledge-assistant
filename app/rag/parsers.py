import re
from pathlib import Path

import pymupdf
from docx import Document as DocxDocument

from app.rag.errors import DocumentProcessingError
from app.rag.types import ParsedSection

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def parse_document(path: Path) -> list[ParsedSection]:
    extension = path.suffix.lower()
    try:
        if extension == ".pdf":
            sections = _parse_pdf(path)
        elif extension == ".docx":
            sections = _parse_docx(path)
        elif extension in {".txt", ".md", ".markdown"}:
            sections = _parse_text(path)
        else:
            raise DocumentProcessingError("Unsupported document type")
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError(
            f"Unable to parse {extension.removeprefix('.').upper()} document"
        ) from exc

    cleaned_sections: list[ParsedSection] = []
    for section in sections:
        cleaned_text = clean_text(section.text)
        if cleaned_text:
            cleaned_sections.append(
                ParsedSection(
                    text=cleaned_text,
                    page_number=section.page_number,
                    paragraph_number=section.paragraph_number,
                )
            )
    if not cleaned_sections:
        raise DocumentProcessingError("Document contains no extractable text")
    return cleaned_sections


def _parse_pdf(path: Path) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    with pymupdf.open(path) as document:
        for page_index, page in enumerate(document, start=1):
            sections.append(
                ParsedSection(
                    text=page.get_text("text"),
                    page_number=page_index,
                )
            )
    return sections


def _parse_docx(path: Path) -> list[ParsedSection]:
    document = DocxDocument(path)
    return [
        ParsedSection(text=paragraph.text, paragraph_number=index)
        for index, paragraph in enumerate(document.paragraphs, start=1)
    ]


def _parse_text(path: Path) -> list[ParsedSection]:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentProcessingError("Text document must use UTF-8 encoding") from exc

    paragraphs = re.split(r"\n\s*\n", content)
    return [
        ParsedSection(text=paragraph, paragraph_number=index)
        for index, paragraph in enumerate(paragraphs, start=1)
    ]
