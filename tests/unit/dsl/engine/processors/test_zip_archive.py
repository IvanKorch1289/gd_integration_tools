"""Unit-тесты ZipArchiveProcessor — Wave [wave:s5/k3-w2-processor-pack-2]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.zip_archive import ZipArchiveProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_zip_archive", True)


@pytest.mark.asyncio
async def test_pack_then_unpack_roundtrip() -> None:
    pack = ZipArchiveProcessor(mode="pack", source="body", to="body.archive")
    files = {"a.txt": "Hello", "b.txt": b"World"}
    ex1 = _ex(files)
    await pack.process(ex1, AsyncMock())
    archive_bytes = ex1.in_message.body["archive"]
    assert isinstance(archive_bytes, bytes) and archive_bytes[:2] == b"PK"

    unpack = ZipArchiveProcessor(
        mode="unpack", source="body.archive", to="body.unpacked"
    )
    ex2 = _ex({"archive": archive_bytes})
    await unpack.process(ex2, AsyncMock())
    unpacked = ex2.in_message.body["unpacked"]
    assert unpacked == {"a.txt": b"Hello", "b.txt": b"World"}


@pytest.mark.asyncio
async def test_pack_invalid_source_fails() -> None:
    proc = ZipArchiveProcessor(mode="pack", source="body", to="body.r")
    ex = _ex("not a dict")
    await proc.process(ex, AsyncMock())
    assert ex.error is not None and "must be dict" in ex.error


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_zip_archive", False)
    proc = ZipArchiveProcessor(mode="pack")
    ex = _ex({"a.txt": "x"})

    await proc.process(ex, AsyncMock())

    assert ex.properties.get("zip_archive_status") == "skipped"
