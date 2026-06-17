import pymupdf
import pytest
from docx import Document as DocxDocument

from app.rag.errors import DocumentProcessingError
from app.rag.parsers import parse_document


def test_parse_txt_and_markdown_paragraphs(tmp_path) -> None:
    text_path = tmp_path / "notes.md"
    text_path.write_text("First paragraph.\n\nSecond paragraph.", encoding="utf-8")

    sections = parse_document(text_path)

    assert [section.text for section in sections] == [
        "First paragraph.",
        "Second paragraph.",
    ]
    assert [section.paragraph_number for section in sections] == [1, 2]


def test_parse_docx_paragraphs(tmp_path) -> None:
    docx_path = tmp_path / "handbook.docx"
    document = DocxDocument()
    document.add_paragraph("First DOCX paragraph")
    document.add_paragraph("Second DOCX paragraph")
    document.save(docx_path)

    sections = parse_document(docx_path)

    assert [section.text for section in sections] == [
        "First DOCX paragraph",
        "Second DOCX paragraph",
    ]
    assert [section.paragraph_number for section in sections] == [1, 2]


def test_parse_pdf_pages(tmp_path) -> None:
    pdf_path = tmp_path / "guide.pdf"
    document = pymupdf.open()
    first_page = document.new_page()
    first_page.insert_text((72, 72), "First PDF page")
    second_page = document.new_page()
    second_page.insert_text((72, 72), "Second PDF page")
    document.save(pdf_path)
    document.close()

    sections = parse_document(pdf_path)

    assert [section.page_number for section in sections] == [1, 2]
    assert "First PDF page" in sections[0].text
    assert "Second PDF page" in sections[1].text


def test_parse_empty_document_fails(tmp_path) -> None:
    empty_path = tmp_path / "empty.txt"
    empty_path.write_text(" \n\n ", encoding="utf-8")

    with pytest.raises(DocumentProcessingError, match="no extractable text"):
        parse_document(empty_path)
