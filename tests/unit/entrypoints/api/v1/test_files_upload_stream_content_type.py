"""ADR-0423 — content-type allowlist для streaming-загрузки.

Контекст
--------
Буферизованная загрузка (``POST /api/v1/storage/upload_file``) проверяет
content-type по allowlist'у (ADR-0422), а streaming-эндпоинт
(``POST /api/v1/storage/upload-stream``) — нет: в S3 попадает любой
content-type, включая исполняемые файлы и HTML. Контракт ответа при этом
менять нельзя.

Проверяется и «до чтения тела»: отклонённый запрос не должен читать поток.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import HTTPException

from src.backend.entrypoints.api.v1.endpoints import files as files_module
from src.backend.entrypoints.api.v1.endpoints.files import upload_stream_handler


class _FakeRequest:
    """Запрос с потоком тела и заголовками."""

    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None):
        """Сохранить chunks потока и заголовки запроса."""
        self._chunks = chunks
        self.headers = headers or {}

    def stream(self) -> AsyncIterator[bytes]:
        """Асинхронный генератор с телом запроса."""
        return self._iter()

    async def _iter(self) -> AsyncIterator[bytes]:
        """Выдать chunks по одному."""
        for chunk in self._chunks:
            yield chunk


class _FakeS3:
    """S3-клиент, считающий прочитанные байты."""

    def __init__(self) -> None:
        """Счётчик прочитанных байт."""
        self.total = 0

    async def put_object_multipart(
        self, *, key: str, stream: Any, content_type: str | None = None
    ) -> str:
        """Прочитать поток и вернуть ETag."""
        async for chunk in stream:
            self.total += len(chunk)
        return "etag"


@pytest.mark.unit
class TestStreamContentTypeAllowlist:
    """``/storage/upload-stream`` принимает только разрешённые content-type."""

    async def test_disallowed_content_type_returns_415(self) -> None:
        """Недопустимый content-type → 415."""
        s3 = _FakeS3()
        request = _FakeRequest([b"x" * 1024])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(files_module, "get_s3_service", lambda: s3)
            with pytest.raises(HTTPException) as exc:
                await upload_stream_handler(
                    request=request,  # type: ignore[arg-type]
                    x_api_key="key",
                    content_type="application/x-msdownload",
                    x_filename="evil.exe",
                )

        assert exc.value.status_code == 415

    async def test_body_is_not_read_for_rejected_content_type(self) -> None:
        """Отклонённый запрос не читает тело."""
        s3 = _FakeS3()
        request = _FakeRequest([b"x" * 1024])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(files_module, "get_s3_service", lambda: s3)
            with pytest.raises(HTTPException):
                await upload_stream_handler(
                    request=request,  # type: ignore[arg-type]
                    x_api_key="key",
                    content_type="text/html",
                    x_filename="page.html",
                )

        assert s3.total == 0, "тело не должно читаться при отклонении"

    async def test_allowed_content_type_is_uploaded(self) -> None:
        """Разрешённый content-type — контракт ответа не меняется."""
        s3 = _FakeS3()
        request = _FakeRequest([b"x" * 1024])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(files_module, "get_s3_service", lambda: s3)
            result = await upload_stream_handler(
                request=request,  # type: ignore[arg-type]
                x_api_key="key",
                content_type="application/octet-stream",
                x_filename="ok.bin",
            )

        assert result == {
            "uploaded": True,
            "key": "ok.bin",
            "etag": "etag",
            "content_type": "application/octet-stream",
        }
        assert s3.total == 1024

    async def test_missing_content_type_keeps_legacy_contract(self) -> None:
        """Без content-type запрос принимается (прежний контракт)."""
        s3 = _FakeS3()
        request = _FakeRequest([b"x" * 16])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(files_module, "get_s3_service", lambda: s3)
            result = await upload_stream_handler(
                request=request,  # type: ignore[arg-type]
                x_api_key="key",
                content_type=None,
                x_filename="ok.bin",
            )

        assert result["uploaded"] is True
        assert result["content_type"] is None
        assert s3.total == 16
