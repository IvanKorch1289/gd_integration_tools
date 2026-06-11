"""Sprint 83 W3: async non-blocking тесты для ArchiveProcessor (zipfile/tarfile).

Проверяем, что sync archive I/O (zipfile.ZipFile, tarfile.open) внутри
``ArchiveProcessor`` выполняется в executor thread, а НЕ блокирует event loop.

**Подход**: patch slow I/O через ``time.sleep(SLEEP_S)`` → запускаем процессор
параллельно с ``asyncio.sleep(SLEEP_S)`` → проверяем elapsed < 1.7 * SLEEP_S.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import io
import tarfile
import threading
import time
import zipfile
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
    ArchiveProcessor,
)

SLEEP_S = 0.10
MAX_PARALLEL_TOTAL_S = SLEEP_S * 1.7


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


def _make_zip_bytes(items: list[tuple[str, bytes]]) -> bytes:
    """Собрать валидный ZIP из списка (name, data)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in items:
            zf.writestr(name, data)
    return buf.getvalue()


def _make_tar_bytes(items: list[tuple[str, bytes]]) -> bytes:
    """Собрать валидный TAR.GZ из списка (name, data)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in items:
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


class TestArchiveProcessorNonBlockingZip:
    """ZIP extract/create — non-blocking."""

    @pytest.mark.asyncio
    async def test_zip_extract_does_not_block_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``archive extract`` (zip) offload-ит zipfile в executor thread."""
        zip_bytes = _make_zip_bytes([("a.txt", b"hello"), ("b.txt", b"world")])

        real_zipfile = zipfile.ZipFile
        thread_holder: list[int] = []
        main_thread = threading.get_ident()

        class SlowZipFile(real_zipfile):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                thread_holder.append(threading.get_ident())
                time.sleep(SLEEP_S)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(zipfile, "ZipFile", SlowZipFile)

        proc = ArchiveProcessor(mode="extract", format="zip")
        ex = _make_exchange(body=zip_bytes)

        start = time.monotonic()
        await asyncio.gather(
            proc.process(ex, AsyncMock()),
            asyncio.sleep(SLEEP_S),
        )
        elapsed = time.monotonic() - start

        assert elapsed < MAX_PARALLEL_TOTAL_S, (
            f"zip extract заблокировал event loop: elapsed={elapsed:.3f}s"
        )
        # Дополнительно: zipfile.ZipFile вызван в НЕ-main thread.
        assert thread_holder[0] != main_thread, (
            f"zipfile.ZipFile вызван в main loop thread (got {thread_holder[0]})"
        )

    @pytest.mark.asyncio
    async def test_zip_create_does_not_block_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``archive create`` (zip) offload-ит zipfile в executor thread."""
        items = [
            {"name": "a.txt", "data": b"hello"},
            {"name": "b.txt", "data": b"world"},
        ]

        real_zipfile = zipfile.ZipFile
        thread_holder: list[int] = []
        main_thread = threading.get_ident()

        class SlowZipFile(real_zipfile):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                thread_holder.append(threading.get_ident())
                time.sleep(SLEEP_S)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(zipfile, "ZipFile", SlowZipFile)

        proc = ArchiveProcessor(mode="create", format="zip")
        ex = _make_exchange(body=items)

        start = time.monotonic()
        await asyncio.gather(
            proc.process(ex, AsyncMock()),
            asyncio.sleep(SLEEP_S),
        )
        elapsed = time.monotonic() - start

        assert elapsed < MAX_PARALLEL_TOTAL_S, (
            f"zip create заблокировал event loop: elapsed={elapsed:.3f}s"
        )
        assert thread_holder[0] != main_thread


class TestArchiveProcessorNonBlockingTar:
    """TAR extract/create — non-blocking."""

    @pytest.mark.asyncio
    async def test_tar_extract_does_not_block_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``archive extract`` (tar) offload-ит tarfile в executor thread."""
        tar_bytes = _make_tar_bytes([("a.txt", b"hello")])

        real_tarfile_open = tarfile.open
        thread_holder: list[int] = []
        main_thread = threading.get_ident()

        def slow_tarfile_open(*args: Any, **kwargs: Any) -> Any:
            thread_holder.append(threading.get_ident())
            time.sleep(SLEEP_S)
            return real_tarfile_open(*args, **kwargs)

        monkeypatch.setattr(tarfile, "open", slow_tarfile_open)

        proc = ArchiveProcessor(mode="extract", format="tar")
        ex = _make_exchange(body=tar_bytes)

        start = time.monotonic()
        await asyncio.gather(
            proc.process(ex, AsyncMock()),
            asyncio.sleep(SLEEP_S),
        )
        elapsed = time.monotonic() - start

        assert elapsed < MAX_PARALLEL_TOTAL_S, (
            f"tar extract заблокировал event loop: elapsed={elapsed:.3f}s"
        )
        assert thread_holder[0] != main_thread

    @pytest.mark.asyncio
    async def test_tar_create_does_not_block_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``archive create`` (tar) offload-ит tarfile в executor thread."""
        items = [
            {"name": "a.txt", "data": b"hello"},
            {"name": "b.txt", "data": b"world"},
        ]

        real_tarfile_open = tarfile.open
        thread_holder: list[int] = []
        main_thread = threading.get_ident()

        def slow_tarfile_open(*args: Any, **kwargs: Any) -> Any:
            thread_holder.append(threading.get_ident())
            time.sleep(SLEEP_S)
            return real_tarfile_open(*args, **kwargs)

        monkeypatch.setattr(tarfile, "open", slow_tarfile_open)

        proc = ArchiveProcessor(mode="create", format="tar")
        ex = _make_exchange(body=items)

        start = time.monotonic()
        await asyncio.gather(
            proc.process(ex, AsyncMock()),
            asyncio.sleep(SLEEP_S),
        )
        elapsed = time.monotonic() - start

        assert elapsed < MAX_PARALLEL_TOTAL_S, (
            f"tar create заблокировал event loop: elapsed={elapsed:.3f}s"
        )
        assert thread_holder[0] != main_thread


class TestArchiveProcessorFunctional:
    """Smoke-тесты корректности (zip round-trip) + проверка что async API не падает."""

    @pytest.mark.asyncio
    async def test_zip_create_then_extract_roundtrip(self) -> None:
        """ZIP: create → extract round-trip возвращает исходные файлы."""
        create_proc = ArchiveProcessor(mode="create", format="zip")
        ex_create = _make_exchange(
            body=[
                {"name": "a.txt", "data": b"hello"},
                {"name": "b.txt", "data": b"world"},
            ]
        )
        await create_proc.process(ex_create, AsyncMock())
        zip_bytes = ex_create.out_message.body
        assert isinstance(zip_bytes, bytes)
        assert zip_bytes[:2] == b"PK"

        extract_proc = ArchiveProcessor(mode="extract", format="zip")
        ex_extract = _make_exchange(body=zip_bytes)
        await extract_proc.process(ex_extract, AsyncMock())
        files = ex_extract.out_message.body
        assert isinstance(files, list)
        names = [f["name"] for f in files]
        assert "a.txt" in names
        assert "b.txt" in names
        a = next(f for f in files if f["name"] == "a.txt")
        assert a["data"] == b"hello"

    @pytest.mark.asyncio
    async def test_tar_create_then_extract_roundtrip(self) -> None:
        """TAR: create → extract round-trip возвращает исходные файлы."""
        create_proc = ArchiveProcessor(mode="create", format="tar")
        ex_create = _make_exchange(
            body=[
                {"name": "x.txt", "data": b"foo"},
                {"name": "y.txt", "data": b"bar"},
            ]
        )
        await create_proc.process(ex_create, AsyncMock())
        tar_bytes = ex_create.out_message.body
        assert isinstance(tar_bytes, bytes)

        extract_proc = ArchiveProcessor(mode="extract", format="tar")
        ex_extract = _make_exchange(body=tar_bytes)
        await extract_proc.process(ex_extract, AsyncMock())
        files = ex_extract.out_message.body
        names = [f["name"] for f in files]
        assert "x.txt" in names
        assert "y.txt" in names
