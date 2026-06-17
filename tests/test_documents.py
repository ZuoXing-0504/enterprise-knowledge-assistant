from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.document import Document, DocumentStatus
from tests.helpers import create_authenticated_user, create_knowledge_base


def mock_document_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.document.process_document.delay",
        lambda document_id: SimpleNamespace(id=f"task-{document_id}"),
    )


async def upload_text_document(
    client: AsyncClient,
    headers: dict[str, str],
    knowledge_base_id: str,
    *,
    filename: str = "notes.txt",
    content: bytes = b"First paragraph.\n\nSecond paragraph.",
) -> Response:
    return await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        headers=headers,
        files={"file": (filename, content, "text/plain")},
    )


async def test_upload_list_get_and_delete_document(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_document_queue(monkeypatch)
    _, headers = await create_authenticated_user(client, email="documents@example.com")
    knowledge_base = await create_knowledge_base(client, headers)

    upload_response = await upload_text_document(
        client,
        headers,
        str(knowledge_base["id"]),
        filename="../../notes.txt",
    )

    assert upload_response.status_code == 201
    document_data = upload_response.json()["data"]
    assert document_data["original_filename"] == "notes.txt"
    assert document_data["status"] == DocumentStatus.PENDING.value
    assert "storage_path" not in document_data

    async with async_session_factory() as session:
        stored_document = (
            await session.execute(select(Document).where(Document.id == UUID(document_data["id"])))
        ).scalar_one()
        stored_path = get_settings().upload_dir / stored_document.storage_path
        assert Path(stored_document.storage_path).name == stored_document.storage_path
        assert stored_path.exists()
        assert stored_document.celery_task_id == f"task-{stored_document.id}"

    list_response = await client.get(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents",
        headers=headers,
    )
    get_response = await client.get(
        f"/api/v1/documents/{document_data['id']}",
        headers=headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["data"]["pagination"]["total"] == 1
    assert get_response.status_code == 200
    assert get_response.json()["data"]["id"] == document_data["id"]

    delete_response = await client.delete(
        f"/api/v1/documents/{document_data['id']}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    assert not stored_path.exists()

    missing_response = await client.get(
        f"/api/v1/documents/{document_data['id']}",
        headers=headers,
    )
    assert missing_response.status_code == 404


async def test_document_access_is_scoped_to_owner(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_document_queue(monkeypatch)
    _, owner_headers = await create_authenticated_user(client, email="owner-docs@example.com")
    _, other_headers = await create_authenticated_user(client, email="other-docs@example.com")
    knowledge_base = await create_knowledge_base(client, owner_headers)
    upload_response = await upload_text_document(
        client,
        owner_headers,
        str(knowledge_base["id"]),
    )
    document_id = upload_response.json()["data"]["id"]

    list_response = await client.get(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents",
        headers=other_headers,
    )
    get_response = await client.get(
        f"/api/v1/documents/{document_id}",
        headers=other_headers,
    )
    delete_response = await client.delete(
        f"/api/v1/documents/{document_id}",
        headers=other_headers,
    )

    assert list_response.status_code == 404
    assert list_response.json()["error"]["code"] == "knowledge_base_not_found"
    for response in (get_response, delete_response):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "document_not_found"


async def test_document_upload_is_scoped_to_knowledge_base_owner(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_document_queue(monkeypatch)
    _, owner_headers = await create_authenticated_user(client, email="upload-owner@example.com")
    _, other_headers = await create_authenticated_user(client, email="upload-other@example.com")
    knowledge_base = await create_knowledge_base(client, owner_headers)

    response = await upload_text_document(
        client,
        other_headers,
        str(knowledge_base["id"]),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "knowledge_base_not_found"
    async with async_session_factory() as session:
        assert (await session.execute(select(Document))).scalars().all() == []


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "error_code"),
    [
        ("malware.exe", "application/octet-stream", b"MZ", "unsupported_file_type"),
        ("fake.pdf", "application/pdf", b"not a pdf", "invalid_file_content"),
        ("fake.docx", "text/plain", b"PK-data", "unsupported_content_type"),
    ],
)
async def test_upload_rejects_invalid_files(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content_type: str,
    content: bytes,
    error_code: str,
) -> None:
    mock_document_queue(monkeypatch)
    _, headers = await create_authenticated_user(client, email="invalid-files@example.com")
    knowledge_base = await create_knowledge_base(client, headers)

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == error_code


async def test_upload_rejects_empty_and_oversized_files(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_document_queue(monkeypatch)
    _, headers = await create_authenticated_user(client, email="file-size@example.com")
    knowledge_base = await create_knowledge_base(client, headers)

    empty_response = await upload_text_document(
        client,
        headers,
        str(knowledge_base["id"]),
        content=b"",
    )
    settings = get_settings()
    settings.max_upload_size_mb = 1
    oversized_response = await upload_text_document(
        client,
        headers,
        str(knowledge_base["id"]),
        content=b"x" * (1024 * 1024 + 1),
    )

    assert empty_response.status_code == 400
    assert empty_response.json()["error"]["code"] == "empty_file"
    assert oversized_response.status_code == 413
    assert oversized_response.json()["error"]["code"] == "file_too_large"


async def test_task_enqueue_failure_is_recorded(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_queue(document_id: str) -> None:
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr("app.services.document.process_document.delay", fail_to_queue)
    _, headers = await create_authenticated_user(client, email="queue-failure@example.com")
    knowledge_base = await create_knowledge_base(client, headers)

    response = await upload_text_document(client, headers, str(knowledge_base["id"]))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "document_task_unavailable"
    async with async_session_factory() as session:
        document = (await session.execute(select(Document))).scalar_one()
        assert document.status == DocumentStatus.FAILED.value
        assert document.error_message == "Document processing task could not be queued"


async def test_deleting_knowledge_base_removes_document_file(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_document_queue(monkeypatch)
    _, headers = await create_authenticated_user(client, email="kb-cleanup@example.com")
    knowledge_base = await create_knowledge_base(client, headers)
    upload_response = await upload_text_document(
        client,
        headers,
        str(knowledge_base["id"]),
    )

    async with async_session_factory() as session:
        document = await session.get(
            Document,
            UUID(upload_response.json()["data"]["id"]),
        )
        assert document is not None
        stored_path = get_settings().upload_dir / document.storage_path
        assert stored_path.exists()

    response = await client.delete(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}",
        headers=headers,
    )

    assert response.status_code == 200
    assert not stored_path.exists()
