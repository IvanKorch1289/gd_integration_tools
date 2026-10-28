"""C2 (ADR-0367) — ArchiveProcessor: zip-slip и капы на распаковку.

Дефекты, закрываемые этим файлом:

1. ``mode="create"`` писал имя записи как есть → zip-slip
   (``../../etc/cron.d/evil``). Ожидание: имя санитизируется через
   ``os.path.basename``; пустое/``.``/``..`` имя — отказ.
2. ``mode="extract"`` не имел кап → zip/tar-bomb (OOM). Ожидание:
   сумма размеров и число записей проверяются ДО чтения, плюс
   per-entry cap на фактически прочитанные байты.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message


def _allow(proc: Any) -> None:
    """Обойти fail-closed capability-гейт (тестируем не capability, а archive)."""
    proc.auth_check = AsyncMock(return_value=True)


def _exchange(body: Any) -> Exchange[Any]:
    """Настоящий Exchange — проверяем status/error, а не mock-вызовы."""
    return Exchange(in_message=Message(body=body, headers={}))


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    """Собрать zip-архив в памяти."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def _tar_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    """Собрать tar.gz-архив в памяти."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestArchiveCreateZipSlip:
    """``mode="create"`` — имя записи санитизируется (zip-slip)."""

    @pytest.mark.asyncio
    async def test_create_zip_sanitizes_traversal_entry_name(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        proc = ArchiveProcessor(mode="create", format="zip")
        _allow(proc)
        ex = _exchange([{"name": "../../etc/cron.d/evil", "data": b"payload"}])

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed, ex.error
        out = ex.out_message.body
        assert isinstance(out, bytes)
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            names = zf.namelist()
        assert names == ["evil"], f"zip-slip: {names}"
        assert not any(".." in n for n in names)

    @pytest.mark.asyncio
    async def test_create_tar_sanitizes_traversal_entry_name(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        proc = ArchiveProcessor(mode="create", format="tar")
        _allow(proc)
        ex = _exchange([{"name": "../../etc/cron.d/evil", "data": b"payload"}])

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed, ex.error
        out = ex.out_message.body
        assert isinstance(out, bytes)
        with tarfile.open(fileobj=io.BytesIO(out)) as tf:
            names = tf.getnames()
        assert names == ["evil"], f"zip-slip: {names}"

    @pytest.mark.asyncio
    async def test_create_zip_rejects_empty_entry_name(self) -> None:
        """Пустое имя записи — отказ (нет смысла создавать безымянную запись)."""
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        proc = ArchiveProcessor(mode="create", format="zip")
        _allow(proc)
        ex = _exchange([{"name": "", "data": b"payload"}])

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "name" in (ex.error or "").lower()

    @pytest.mark.asyncio
    async def test_create_zip_rejects_dotdot_entry_name(self) -> None:
        """Имя ``..`` после basename — ссылка на каталог, а не файл."""
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        proc = ArchiveProcessor(mode="create", format="zip")
        _allow(proc)
        ex = _exchange([{"name": "..", "data": b"payload"}])

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed


class TestArchiveExtractCaps:
    """``mode="extract"`` — капы на распаковку (zip/tar-bomb)."""

    def test_module_caps_are_production_values(self) -> None:
        """Капы — модульные константы, без новых config-ключей."""
        from src.backend.dsl.engine.processors.rpa.operations import archiveprocessor

        assert archiveprocessor._MAX_UNPACK_BYTES == 64 * 1024 * 1024
        assert archiveprocessor._MAX_ENTRIES == 1000

    @pytest.mark.asyncio
    async def test_extract_rejects_too_many_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.operations import archiveprocessor
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        monkeypatch.setattr(archiveprocessor, "_MAX_ENTRIES", 2)
        proc = ArchiveProcessor(mode="extract", format="zip")
        _allow(proc)
        ex = _exchange(_zip_bytes([(f"f{i}.txt", b"x") for i in range(3)]))

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "too many entries" in (ex.error or "")

    @pytest.mark.asyncio
    async def test_extract_rejects_total_size_over_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сумма размеров > капа → отказ ДО чтения содержимого."""
        from src.backend.dsl.engine.processors.rpa.operations import archiveprocessor
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        # Кап выше per-entry размера, но ниже суммы → срабатывает total-кап.
        monkeypatch.setattr(archiveprocessor, "_MAX_UNPACK_BYTES", 150)
        proc = ArchiveProcessor(mode="extract", format="zip")
        _allow(proc)
        ex = _exchange(_zip_bytes([("a.txt", b"a" * 100), ("b.txt", b"b" * 100)]))

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "too large" in (ex.error or "")

    @pytest.mark.asyncio
    async def test_extract_rejects_entry_over_per_entry_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Одна запись больше per-entry капа → отказ."""
        from src.backend.dsl.engine.processors.rpa.operations import archiveprocessor
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        monkeypatch.setattr(archiveprocessor, "_MAX_UNPACK_BYTES", 10)
        proc = ArchiveProcessor(mode="extract", format="zip")
        _allow(proc)
        ex = _exchange(_zip_bytes([("big.bin", b"x" * 100)]))

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "too large" in (ex.error or "")

    @pytest.mark.asyncio
    async def test_extract_tar_rejects_too_many_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.operations import archiveprocessor
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        monkeypatch.setattr(archiveprocessor, "_MAX_ENTRIES", 1)
        proc = ArchiveProcessor(mode="extract", format="tar")
        _allow(proc)
        ex = _exchange(_tar_bytes([("a.txt", b"a"), ("b.txt", b"b")]))

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "too many entries" in (ex.error or "")

    @pytest.mark.asyncio
    async def test_extract_tar_rejects_total_size_over_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.operations import archiveprocessor
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        monkeypatch.setattr(archiveprocessor, "_MAX_UNPACK_BYTES", 150)
        proc = ArchiveProcessor(mode="extract", format="tar")
        _allow(proc)
        ex = _exchange(_tar_bytes([("a.txt", b"a" * 100), ("b.txt", b"b" * 100)]))

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "too large" in (ex.error or "")

    @pytest.mark.asyncio
    async def test_extract_normal_archive_still_works(self) -> None:
        """Регресс: обычный архив распаковывается как раньше."""
        from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
            ArchiveProcessor,
        )

        proc = ArchiveProcessor(mode="extract", format="zip")
        _allow(proc)
        ex = _exchange(_zip_bytes([("a.txt", b"hello"), ("b.txt", b"world")]))

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed, ex.error
        files = ex.out_message.body
        assert isinstance(files, list)
        assert sorted(f["name"] for f in files) == ["a.txt", "b.txt"]
        assert sorted(f["data"] for f in files) == [b"hello", b"world"]
