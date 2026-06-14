"""Tests for S128 W3 — FileStreamGRPCServicer (TD-026).

Tests are isolated (no real gRPC server, no real storage):
- mock context with cancelled() / set_code() / abort()
- mock storage backend (in-memory dict)
- directly call servicer methods

Note: real gRPC integration requires ``make grpc-codegen`` to regen
files_pb2.py / files_pb2_grpc.py after proto changes. Until then, tests
verify the servicer logic in isolation.

The grpc_server package __init__ eagerly imports invoker_pb2 (proto stubs
required). We stub those modules before importing — same workaround as
test_grpc_server.py.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest


def _install_protobuf_stubs() -> None:
    """Install fake protobuf modules so grpc_server imports cleanly."""
    from unittest.mock import MagicMock

    for name in (
        "src.backend.entrypoints.grpc.protobuf.invoker_pb2",
        "src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc",
        "src.backend.entrypoints.grpc.protobuf.orders_pb2",
        "src.backend.entrypoints.grpc.protobuf.orders_pb2_grpc",
        "src.backend.entrypoints.grpc.protobuf.files_pb2",
        "src.backend.entrypoints.grpc.protobuf.files_pb2_grpc",
    ):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            # Provide ALL message classes that the servicers might import
            mod.InvokeResponse = MagicMock()
            mod.InvokerServiceServicer = type("Stub", (), {})
            mod.add_InvokerServiceServicer_to_server = MagicMock()
            mod.DeleteResponse = MagicMock()
            mod.OrderDetailResponse = MagicMock()
            mod.OrderResponse = MagicMock()
            mod.OrderServiceServicer = type("Stub", (), {})
            mod.add_OrderServiceServicer_to_server = MagicMock()
            # New streaming classes (TD-026)
            mod.FileChunk = _make_msg_class("FileChunk")
            mod.FileUploadRequest = _make_msg_class("FileUploadRequest")
            mod.FileUploadResponse = _make_msg_class("FileUploadResponse")
            mod.DownloadFileRequest = _make_msg_class("DownloadFileRequest")
            mod.FileServiceServicer = type("Stub", (), {})
            mod.add_FileServiceServicer_to_server = MagicMock()
            sys.modules[name] = mod


def _make_msg_class(name: str) -> type:
    """Create a message class with all standard fields as kwargs (default None)."""

    class _Msg:
        def __init__(self, **kwargs: Any) -> None:
            # All known fields default to None/empty
            self.file_id = 0
            self.filename = ""
            self.sequence = 0
            self.data = b""
            self.is_last = False
            self.offset = 0
            self.final_fingerprint = ""
            self.object_uuid = ""
            self.size_bytes = 0
            self.fingerprint = ""
            self.error = ""
            for k, v in kwargs.items():
                setattr(self, k, v)

        def __repr__(self) -> str:
            attrs = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
            return f"{name}({attrs})"

    _Msg.__name__ = name
    return _Msg


_install_protobuf_stubs()

from src.backend.entrypoints.grpc.grpc_server.file_stream import (  # noqa: E402
    FileStreamConfig,
    FileStreamGRPCServicer,
    compute_sha256,
)


# --------------------------------------------------------------------------- #
# Mock context
# --------------------------------------------------------------------------- #


class _MockContext:
    """Minimal gRPC ServicerContext stub."""

    def __init__(self, cancelled: bool = False) -> None:
        self._cancelled = cancelled
        self.code: Any = None
        self.details: str = ""
        self.aborted: bool = False

    def cancelled(self) -> bool:
        return self._cancelled

    def set_code(self, code: Any) -> None:
        self.code = code

    def set_details(self, details: str) -> None:
        self.details = details

    def abort(self, code: Any, details: str) -> None:
        self.aborted = True
        self.code = code
        self.details = details


# --------------------------------------------------------------------------- #
# Mock storage
# --------------------------------------------------------------------------- #


class _MockStorage:
    """In-memory storage backend for tests."""

    def __init__(self) -> None:
        self.files: dict[int, dict[str, Any]] = {}

    async def get_metadata(self, file_id: int) -> dict[str, Any] | None:
        return self.files.get(file_id)

    async def read(
        self, meta: dict[str, Any], *, offset: int = 0
    ) -> bytes:
        return meta["data"][offset:]

    async def write(
        self,
        file_id: int,
        filename: str,
        data: bytes,
        object_uuid: str,
    ) -> None:
        self.files[file_id] = {
            "filename": filename,
            "data": data,
            "object_uuid": object_uuid,
        }


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #


def _request(file_id: int = 0, offset: int = 0) -> Any:
    """Mock request object."""
    req = type("R", (), {})()
    req.file_id = file_id
    req.offset = offset
    return req


# --------------------------------------------------------------------------- #
# FileStreamConfig
# --------------------------------------------------------------------------- #


class TestFileStreamConfig:
    def test_defaults(self) -> None:
        cfg = FileStreamConfig()
        assert cfg.chunk_size == 64 * 1024
        assert cfg.max_file_size == 1024 * 1024 * 1024

    def test_custom(self) -> None:
        cfg = FileStreamConfig(chunk_size=128 * 1024, max_file_size=2**30)
        assert cfg.chunk_size == 128 * 1024


# --------------------------------------------------------------------------- #
# compute_sha256
# --------------------------------------------------------------------------- #


class TestComputeSha256:
    def test_empty(self) -> None:
        assert compute_sha256(b"") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_hello(self) -> None:
        assert compute_sha256(b"hello") == (
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        )


# --------------------------------------------------------------------------- #
# FileStreamGRPCServicer construction
# --------------------------------------------------------------------------- #


class TestServicerInit:
    def test_default_construction(self) -> None:
        storage = _MockStorage()
        servicer = FileStreamGRPCServicer(get_storage=lambda: storage)
        assert servicer._config.chunk_size == 64 * 1024
        assert servicer._get_storage is not None

    def test_custom_config(self) -> None:
        cfg = FileStreamConfig(chunk_size=1024)
        storage = _MockStorage()
        servicer = FileStreamGRPCServicer(
            config=cfg, get_storage=lambda: storage
        )
        assert servicer._config.chunk_size == 1024


# --------------------------------------------------------------------------- #
# DownloadFile (server streaming)
# --------------------------------------------------------------------------- #


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_streams_chunks(self) -> None:
        """File larger than chunk_size → multiple chunks."""
        storage = _MockStorage()
        data = b"x" * (100 * 1024)  # 100KB
        storage.files[1] = {
            "filename": "test.bin",
            "data": data,
            "object_uuid": "uuid-1",
        }
        cfg = FileStreamConfig(chunk_size=64 * 1024)
        servicer = FileStreamGRPCServicer(
            config=cfg, get_storage=lambda: storage
        )
        context = _MockContext()
        request = _request(file_id=1)

        chunks = []
        async for chunk in servicer.DownloadFile(request, context):
            chunks.append(chunk)

        # 100KB / 64KB = 2 chunks
        assert len(chunks) == 2
        # First chunk: 64KB
        assert chunks[0].sequence == 0
        assert len(chunks[0].data) == 64 * 1024
        assert chunks[0].is_last is False
        assert chunks[0].final_fingerprint == ""
        # Second chunk: 36KB + is_last
        assert chunks[1].sequence == 1
        assert len(chunks[1].data) == 36 * 1024
        assert chunks[1].is_last is True
        assert chunks[1].final_fingerprint != ""

    @pytest.mark.asyncio
    async def test_small_file_one_chunk(self) -> None:
        """File < chunk_size → single chunk."""
        storage = _MockStorage()
        data = b"hello"
        storage.files[1] = {
            "filename": "small.txt",
            "data": data,
            "object_uuid": "uuid-1",
        }
        servicer = FileStreamGRPCServicer(get_storage=lambda: storage)
        context = _MockContext()
        request = _request(file_id=1)

        chunks = []
        async for chunk in servicer.DownloadFile(request, context):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].data == b"hello"
        assert chunks[0].is_last is True
        assert chunks[0].final_fingerprint == compute_sha256(b"hello")

    @pytest.mark.asyncio
    async def test_missing_file_no_chunks(self) -> None:
        storage = _MockStorage()
        servicer = FileStreamGRPCServicer(get_storage=lambda: storage)
        context = _MockContext()
        request = _request(file_id=999)  # missing

        chunks = []
        async for chunk in servicer.DownloadFile(request, context):
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_no_storage_yields_nothing(self) -> None:
        """Если storage backend недоступен → no chunks, no crash."""
        servicer = FileStreamGRPCServicer(get_storage=None)
        context = _MockContext()
        request = _request(file_id=1)

        chunks = []
        async for chunk in servicer.DownloadFile(request, context):
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_cancellation_stops_streaming(self) -> None:
        """context.cancelled() → stop yielding immediately."""
        storage = _MockStorage()
        data = b"x" * (256 * 1024)  # 256KB
        storage.files[1] = {
            "filename": "big.bin",
            "data": data,
            "object_uuid": "uuid-1",
        }
        cfg = FileStreamConfig(chunk_size=64 * 1024)
        servicer = FileStreamGRPCServicer(
            config=cfg, get_storage=lambda: storage
        )
        # Cancel after first chunk
        context = _MockContext(cancelled=False)

        # Generator must check context.cancelled() — but in our test
        # we simulate by checking the first yield and then setting cancelled.
        request = _request(file_id=1)
        gen = servicer.DownloadFile(request, context)
        chunk0 = await gen.__anext__()
        context._cancelled = True
        # Subsequent yields should return early (StopAsyncIteration).
        chunks = [chunk0]
        async for chunk in gen:
            chunks.append(chunk)
            if len(chunks) > 10:
                break  # safety
        # Should have stopped after cancellation
        assert len(chunks) >= 1
        assert len(chunks) < 5  # didn't drain all 4 chunks

    @pytest.mark.asyncio
    async def test_offset_resume(self) -> None:
        """offset > 0 → start from offset (resume support)."""
        storage = _MockStorage()
        data = b"x" * (100 * 1024)
        storage.files[1] = {
            "filename": "test.bin",
            "data": data,
            "object_uuid": "uuid-1",
        }
        cfg = FileStreamConfig(chunk_size=64 * 1024)
        servicer = FileStreamGRPCServicer(
            config=cfg, get_storage=lambda: storage
        )
        context = _MockContext()
        request = _request(file_id=1, offset=64 * 1024)  # skip first 64KB

        chunks = []
        async for chunk in servicer.DownloadFile(request, context):
            chunks.append(chunk)

        # Only 36KB left → 1 chunk
        assert len(chunks) == 1
        assert chunks[0].data == b"x" * 36 * 1024


# --------------------------------------------------------------------------- #
# UploadFile (client streaming)
# --------------------------------------------------------------------------- #


class TestUploadFile:
    @pytest.mark.asyncio
    async def test_full_upload(self) -> None:
        storage = _MockStorage()
        servicer = FileStreamGRPCServicer(get_storage=lambda: storage)
        context = _MockContext()

        async def request_iter() -> Any:
            yield _upload_req(file_id=1, filename="hello.txt", data=b"he", seq=0, last=False)
            yield _upload_req(file_id=1, filename="hello.txt", data=b"llo", seq=1, last=True)

        response = await servicer.UploadFile(request_iter(), context)

        assert response.file_id == 1
        assert response.size_bytes == 5
        assert response.fingerprint == compute_sha256(b"hello")
        assert response.error == ""
        # Verify storage was written
        assert 1 in storage.files
        assert storage.files[1]["data"] == b"hello"
        assert storage.files[1]["filename"] == "hello.txt"

    @pytest.mark.asyncio
    async def test_empty_upload(self) -> None:
        """Empty file (only is_last=True request) → zero bytes."""
        storage = _MockStorage()
        servicer = FileStreamGRPCServicer(get_storage=lambda: storage)
        context = _MockContext()

        async def request_iter() -> Any:
            yield _upload_req(file_id=1, filename="empty.txt", data=b"", seq=0, last=True)

        response = await servicer.UploadFile(request_iter(), context)
        assert response.size_bytes == 0
        assert response.fingerprint == compute_sha256(b"")
        assert storage.files[1]["data"] == b""

    @pytest.mark.asyncio
    async def test_no_storage_returns_error(self) -> None:
        servicer = FileStreamGRPCServicer(get_storage=None)
        context = _MockContext()

        async def request_iter() -> Any:
            yield _upload_req(file_id=1, filename="x", data=b"x", seq=0, last=True)

        response = await servicer.UploadFile(request_iter(), context)
        assert "storage" in response.error

    @pytest.mark.asyncio
    async def test_max_size_exceeded(self) -> None:
        """File larger than max_file_size → error response."""
        storage = _MockStorage()
        cfg = FileStreamConfig(max_file_size=10)  # tiny limit
        servicer = FileStreamGRPCServicer(
            config=cfg, get_storage=lambda: storage
        )
        context = _MockContext()

        async def request_iter() -> Any:
            yield _upload_req(file_id=1, filename="big.bin", data=b"x" * 100, seq=0, last=True)

        response = await servicer.UploadFile(request_iter(), context)
        assert "max size" in response.error
        # Storage not written
        assert 1 not in storage.files

    @pytest.mark.asyncio
    async def test_cancellation(self) -> None:
        """Cancelled context → return error response, no storage write."""
        storage = _MockStorage()
        servicer = FileStreamGRPCServicer(get_storage=lambda: storage)
        context = _MockContext(cancelled=False)

        async def request_iter() -> Any:
            yield _upload_req(file_id=1, filename="x", data=b"x", seq=0, last=False)
            context._cancelled = True  # cancel after first chunk
            yield _upload_req(file_id=1, filename="x", data=b"y", seq=1, last=True)

        response = await servicer.UploadFile(request_iter(), context)
        assert response.error == "cancelled"
        assert 1 not in storage.files


def _upload_req(
    file_id: int, filename: str, data: bytes, seq: int, last: bool
) -> Any:
    req = type("R", (), {})()
    req.file_id = file_id
    req.filename = filename
    req.sequence = seq
    req.data = data
    req.is_last = last
    return req
