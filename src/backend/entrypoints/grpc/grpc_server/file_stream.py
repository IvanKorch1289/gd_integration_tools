"""S128 W3 — :class:`FileStreamGRPCServicer`: gRPC streaming для Files (TD-026).

Реализует 2 streaming RPC для :class:`FileService`:
- ``DownloadFile`` (server streaming) — отдаёт файл чанками по 64KB
- ``UploadFile`` (client streaming) — принимает файл чанками

Паттерн:
- Sequence numbers для reorder detection (клиент/сервер могут
  реассемблировать после network issues)
- Final chunk flag ``is_last`` — server commit / client EOF detection
- SHA-256 fingerprint в final chunk / response — integrity check
- Chunk size 64KB default (configurable через :class:`FileStreamConfig`)

Wire-ready: требует ``make grpc-codegen`` для регенерации
``files_pb2.py`` / ``files_pb2_grpc.py`` после добавления RPCs в
``files.proto`` (S128 W3). До этого servicer может быть протестирован
изолированно (mock context), но не зарегистрирован в gRPC server.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from src.backend.entrypoints.grpc.grpc_server.base import BaseGRPCServicer
from src.backend.entrypoints.grpc.protobuf.files_pb2_grpc import (  # S131 W2 (TD-026 cont. full wire-up)
    FileServiceServicer,
)

# Late import: files_pb2 (с DownloadFile/UploadFile) regen-зависимый.
# Rule #105: late import для circular avoidance + optional codegen deps.

__all__ = ("FileStreamConfig", "FileStreamGRPCServicer", "compute_sha256")


@dataclass(slots=True)
class FileStreamConfig:
    """Конфигурация streaming.

    Attributes:
        chunk_size: Размер chunk в байтах (default 64KB).
        max_file_size: Макс. размер файла в байтах (default 1GB).
    """

    chunk_size: int = 64 * 1024
    max_file_size: int = 1024 * 1024 * 1024


def compute_sha256(data: bytes) -> str:
    """SHA-256 hex digest от data."""
    return hashlib.sha256(data).hexdigest()


class FileStreamGRPCServicer(BaseGRPCServicer, FileServiceServicer):
    """gRPC servicer для streaming file operations (S128 W3 / TD-026, S131 W2 wire-up).

    Реализует 2 streaming RPC:
    - ``async DownloadFile(request, context) -> AsyncIterator[FileChunk]``
    - ``async UploadFile(request_iterator, context) -> FileUploadResponse``

    Multiple inheritance (``BaseGRPCServicer, FileServiceServicer``) —
    S131 W2 завершает wire-up, начатый S128 W3. ``FileServiceServicer``
    сгенерирован из ``files.proto`` (``make grpc-codegen`` regen, S131 W2):
    ``src/backend/entrypoints/grpc/protobuf/files_pb2_grpc.py``.

    Регистрация в gRPC server — ``grpc_server/server.py::serve()``
    (``add_FileServiceServicer_to_server(FileStreamGRPCServicer(), grpc_server)``).

    До полной активации servicer тестируется в изоляции (mock context),
    см. ``tests/unit/entrypoints/grpc/test_file_stream.py``.
    """

    def __init__(
        self,
        config: FileStreamConfig | None = None,
        *,
        # Storage backend dependency — late binding для тестируемости.
        get_storage: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__()
        self._config = config or FileStreamConfig()
        self._get_storage = get_storage
        self.logger.info("FileStreamGRPCServicer инициализирован")

    async def DownloadFile(  # type: ignore[no-untyped-def]
        self, request, context
    ) -> AsyncIterator[Any]:
        """Server streaming: отдаёт файл чанками.

        Args:
            request: ``DownloadFileRequest`` (file_id, offset).
            context: gRPC ServicerContext (для cancellation/error).

        Yields:
            :class:`FileChunk` последовательно. Последний chunk имеет
            ``is_last=True`` и заполненный ``final_fingerprint``.
        """
        # Late import: files_pb2 regen-зависимый (модули protobuf — динамически
        # генерируются protoc; mypy не видит message-классы).
        from src.backend.entrypoints.grpc.protobuf import (
            files_pb2,  # type: ignore[attr-defined]
        )

        FileChunk = files_pb2.FileChunk  # type: ignore[attr-defined]

        storage = self._get_storage() if self._get_storage else None
        if storage is None:
            return

        # Fetch metadata
        file_meta = await storage.get_metadata(request.file_id)
        if file_meta is None:
            return

        data = await storage.read(file_meta, offset=request.offset)
        sequence = 0
        fingerprint = hashlib.sha256()
        for i in range(0, len(data), self._config.chunk_size):
            if context.cancelled():
                self.logger.warning(
                    "DownloadFile cancelled: file_id=%s, sequence=%d",
                    request.file_id,
                    sequence,
                )
                return
            chunk_data = data[i : i + self._config.chunk_size]
            fingerprint.update(chunk_data)
            is_last = i + self._config.chunk_size >= len(data)
            yield FileChunk(  # type: ignore[operator]
                sequence=sequence,
                data=chunk_data,
                final_fingerprint=(fingerprint.hexdigest() if is_last else ""),
                is_last=is_last,
            )
            sequence += 1

    async def UploadFile(  # type: ignore[no-untyped-def]
        self, request_iterator, context
    ) -> Any:
        """Client streaming: принимает файл чанками.

        Args:
            request_iterator: AsyncIterator[FileUploadRequest].
            context: gRPC ServicerContext.

        Returns:
            :class:`FileUploadResponse` с file_id, object_uuid, size, fingerprint.
        """
        from src.backend.entrypoints.grpc.protobuf import (
            files_pb2,  # type: ignore[attr-defined]
        )

        FileUploadResponse = files_pb2.FileUploadResponse  # type: ignore[attr-defined]

        storage = self._get_storage() if self._get_storage else None
        if storage is None:
            return FileUploadResponse(error="storage backend недоступен")  # type: ignore[operator]

        buffer = bytearray()
        file_id = 0
        filename = ""
        fingerprint = hashlib.sha256()
        total_chunks = 0
        async for request in request_iterator:
            if context.cancelled():
                self.logger.warning(
                    "UploadFile cancelled: file_id=%s, chunks=%d", file_id, total_chunks
                )
                return FileUploadResponse(error="cancelled")  # type: ignore[operator]
            file_id = request.file_id or file_id
            filename = filename or request.filename
            if request.data:
                buffer.extend(request.data)
                fingerprint.update(request.data)
            total_chunks += 1
            if request.is_last:
                break

        if len(buffer) > self._config.max_file_size:
            return FileUploadResponse(  # type: ignore[operator]
                file_id=file_id,
                error=f"file exceeds max size {self._config.max_file_size}",
            )

        object_uuid = str(uuid.uuid4())
        await storage.write(
            file_id=file_id,
            filename=filename,
            data=bytes(buffer),
            object_uuid=object_uuid,
        )

        return FileUploadResponse(  # type: ignore[operator]
            file_id=file_id,
            object_uuid=object_uuid,
            size_bytes=len(buffer),
            fingerprint=fingerprint.hexdigest(),
        )
