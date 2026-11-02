"""ADR-0422 — лимиты загрузки файлов (размер + content-type).

Контекст дефекта
----------------
``POST /api/v1/storage/upload_file`` делал ``await file.read()`` — **весь**
файл читался в RAM без ограничения размера и без проверки content-type.
Streaming-эндпоинт ``/api/v1/storage/upload-stream`` лимита тоже не имел:
тело могло оказаться любого размера.

После ADR-0422:

* файл читается **чанками** с жёстким лимитом размера;
* превышение лимита → ``413`` (файл целиком в память не попадает);
* неподдерживаемый content-type → ``415``;
* обычная (не превышающая лимит) загрузка сохраняет прежний контракт
  ответа (``uploaded`` / ``filename`` / ``key`` / ``size`` / …).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import HTTPException

from src.backend.entrypoints.api.v1.endpoints import files as files_module
from src.backend.entrypoints.api.v1.endpoints.files import (
    MAX_STREAM_UPLOAD_BYTES,
    MAX_UPLOAD_BYTES,
    upload_file_handler,
    upload_stream_handler,
)

CHUNK = 1024 * 1024


class _FakeUpload:
    """Минимальный аналог ``UploadFile`` с контролем чтения."""

    def __init__(
        self,
        total_size: int,
        content_type: str | None = "application/pdf",
        filename: str = "doc.pdf",
    ) -> None:
        """Задать объём, content-type и имя файла."""
        self._remaining = total_size
        self.content_type = content_type
        self.filename = filename
        self.headers = {"content-disposition": 'form-data; name="file"'}
        self.bytes_read = 0
        self.read_all_called = False

    async def read(self, size: int = -1) -> bytes:
        """Прочитать не более ``size`` байт (учёт объёма прочитанного)."""
        if size is None or size < 0:
            self.read_all_called = True
            chunk = b"x" * self._remaining
        else:
            chunk = b"x" * min(size, self._remaining)
        self._remaining -= len(chunk)
        self.bytes_read += len(chunk)
        return chunk


class _FakeRequest:
    """Запрос с потоком тела и заголовками."""

    def __init__(
        self, chunks: list[bytes], headers: dict[str, str] | None = None
    ) -> None:
        """Сохранить chunks потока и заголовки запроса."""
        self._chunks = chunks
        self.headers = headers or {}

    def stream(self) -> AsyncIterator[bytes]:
        """Асинхронный генератор с телом запроса."""
        return self._iter()

    async def _iter(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class _FakeS3:
    """S3-клиент, вычитывающий поток целиком."""

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
class TestBufferedUploadLimits:
    """``/storage/upload_file``: лимит размера и content-type."""

    async def test_oversized_file_returns_413(self) -> None:
        """Файл больше лимита → 413."""
        upload = _FakeUpload(total_size=MAX_UPLOAD_BYTES + 1)
        with pytest.raises(HTTPException) as exc:
            await upload_file_handler(
                request=_FakeRequest([]),  # type: ignore[arg-type]
                file=upload,  # type: ignore[arg-type]
                x_api_key="key",
            )
        assert exc.value.status_code == 413

    async def test_oversized_file_is_not_read_fully(self) -> None:
        """Превышение лимита обнаруживается ДО чтения файла целиком."""
        upload = _FakeUpload(total_size=MAX_UPLOAD_BYTES * 4)
        with pytest.raises(HTTPException) as exc:
            await upload_file_handler(
                request=_FakeRequest([]),  # type: ignore[arg-type]
                file=upload,  # type: ignore[arg-type]
                x_api_key="key",
            )
        assert exc.value.status_code == 413
        assert upload.read_all_called is False, "файл нельзя читать целиком в RAM"
        assert upload.bytes_read <= MAX_UPLOAD_BYTES + CHUNK, (
            "прочитано больше лимита — память не защищена"
        )

    async def test_disallowed_content_type_returns_415(self) -> None:
        """Недопустимый content-type → 415."""
        upload = _FakeUpload(total_size=10, content_type="application/x-msdownload")
        with pytest.raises(HTTPException) as exc:
            await upload_file_handler(
                request=_FakeRequest([]),  # type: ignore[arg-type]
                file=upload,  # type: ignore[arg-type]
                x_api_key="key",
            )
        assert exc.value.status_code == 415

    async def test_file_within_limit_is_uploaded(self) -> None:
        """Файл в пределах лимита загружается, контракт ответа сохранён."""
        upload = _FakeUpload(total_size=2048, content_type="application/pdf")

        class _AV:
            async def scan_and_upload_file(self, **kwargs: Any) -> dict[str, Any]:
                return {
                    "uploaded": True,
                    "filename": kwargs["filename"],
                    "key": "s3/key.pdf",
                    "scan_result": {"status": "clean"},
                }

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(files_module, "get_av_service", lambda: _AV())
            result = await upload_file_handler(
                request=_FakeRequest([]),  # type: ignore[arg-type]
                file=upload,  # type: ignore[arg-type]
                x_api_key="key",
            )

        assert result["uploaded"] is True
        assert result["size"] == 2048
        assert result["key"] == "s3/key.pdf"
        assert upload.read_all_called is False


@pytest.mark.unit
class TestStreamingUploadLimits:
    """``/storage/upload-stream``: лимит по потоку и по Content-Length."""

    async def test_stream_over_limit_returns_413(self) -> None:
        """Поток больше лимита → 413."""
        s3 = _FakeS3()
        chunks = [b"x" * (16 * 1024 * 1024) for _ in range(80)]
        request = _FakeRequest(chunks)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(files_module, "get_s3_service", lambda: s3)
            with pytest.raises(HTTPException) as exc:
                await upload_stream_handler(
                    request=request,  # type: ignore[arg-type]
                    x_api_key="key",
                    content_type="application/octet-stream",
                    x_filename="big.bin",
                )

        assert exc.value.status_code == 413
        assert s3.total <= MAX_STREAM_UPLOAD_BYTES + 16 * 1024 * 1024

    async def test_content_length_over_limit_returns_413(self) -> None:
        """Content-Length больше лимита → 413 без чтения тела."""
        s3 = _FakeS3()
        request = _FakeRequest(
            [b"x" * 1024], headers={"content-length": str(MAX_STREAM_UPLOAD_BYTES + 1)}
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(files_module, "get_s3_service", lambda: s3)
            with pytest.raises(HTTPException) as exc:
                await upload_stream_handler(
                    request=request,  # type: ignore[arg-type]
                    x_api_key="key",
                    content_type="application/octet-stream",
                    x_filename="big.bin",
                )

        assert exc.value.status_code == 413
        assert s3.total == 0, "тело не должно читаться при заведомом превышении"

    async def test_stream_within_limit_is_uploaded(self) -> None:
        """Поток в пределах лимита загружается, контракт ответа сохранён."""
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

        assert result["uploaded"] is True
        assert result["etag"] == "etag"
        assert s3.total == 1024
