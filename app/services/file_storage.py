import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import aiofiles
from anyio import to_thread
from fastapi import UploadFile, status

from app.core.config import Settings
from app.core.exceptions import AppError

ALLOWED_CONTENT_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
}


@dataclass(frozen=True, slots=True)
class StoredFile:
    original_filename: str
    storage_path: str
    content_type: str
    file_size: int


class FileStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def save_upload(self, upload: UploadFile) -> StoredFile:
        original_filename = self._safe_original_filename(upload.filename)
        extension = Path(original_filename).suffix.lower()
        content_type = (upload.content_type or "application/octet-stream").split(";", 1)[0].lower()
        if extension not in ALLOWED_CONTENT_TYPES:
            raise AppError(
                code="unsupported_file_type",
                message="Only PDF, DOCX, TXT and Markdown files are supported",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        if content_type not in ALLOWED_CONTENT_TYPES[extension]:
            raise AppError(
                code="unsupported_content_type",
                message="File content type does not match the supported document type",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        root = self.settings.upload_dir.resolve()
        await to_thread.run_sync(root.mkdir, 0o755, True, True)
        storage_path = f"{uuid4()}{extension}"
        final_path = self.resolve(storage_path)
        temporary_path = final_path.with_suffix(f"{final_path.suffix}.part")
        file_size = 0
        header = b""

        try:
            async with aiofiles.open(temporary_path, "wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    file_size += len(chunk)
                    if file_size > self.settings.max_upload_size_bytes:
                        raise AppError(
                            code="file_too_large",
                            message=(
                                f"File exceeds the {self.settings.max_upload_size_mb} MB limit"
                            ),
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        )
                    if len(header) < 8:
                        header += chunk[: 8 - len(header)]
                    await output.write(chunk)

            if file_size == 0:
                raise AppError(
                    code="empty_file",
                    message="Uploaded file is empty",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            self._validate_signature(extension, header)
            await to_thread.run_sync(os.replace, temporary_path, final_path)
        except Exception:
            await self.delete_path(temporary_path)
            raise
        finally:
            await upload.close()

        return StoredFile(
            original_filename=original_filename,
            storage_path=storage_path,
            content_type=content_type,
            file_size=file_size,
        )

    def resolve(self, storage_path: str) -> Path:
        root = self.settings.upload_dir.resolve()
        resolved = (root / storage_path).resolve()
        if resolved.parent != root:
            raise ValueError("Storage path escapes the upload directory")
        return resolved

    async def delete(self, storage_path: str) -> None:
        await self.delete_path(self.resolve(storage_path))

    async def delete_many(self, storage_paths: list[str]) -> None:
        for storage_path in storage_paths:
            await self.delete(storage_path)

    async def delete_path(self, path: Path) -> None:
        await to_thread.run_sync(path.unlink, True)

    @staticmethod
    def _safe_original_filename(filename: str | None) -> str:
        if not filename:
            raise AppError(
                code="missing_filename",
                message="Uploaded file must have a filename",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        safe_name = Path(filename.replace("\\", "/")).name.strip()
        if not safe_name or len(safe_name) > 255:
            raise AppError(
                code="invalid_filename",
                message="Uploaded filename is invalid",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return safe_name

    @staticmethod
    def _validate_signature(extension: str, header: bytes) -> None:
        valid = True
        if extension == ".pdf":
            valid = header.startswith(b"%PDF-")
        elif extension == ".docx":
            valid = header.startswith(b"PK")
        if not valid:
            raise AppError(
                code="invalid_file_content",
                message="File content does not match its extension",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
