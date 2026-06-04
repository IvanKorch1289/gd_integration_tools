"""Unit-tests for FileSink."""

# ruff: noqa: S101

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.file_sink import FileSink


@pytest.fixture
def tmp_sink_file(tmp_path: Path) -> Path:
    return tmp_path / "sink_output.ndjson"


@pytest.mark.asyncio
async def test_kind_is_file() -> None:
    sink = FileSink(sink_id="f1", path="/tmp/x")
    assert sink.kind == SinkKind.FILE


@pytest.mark.asyncio
async def test_append_dict_payload(tmp_sink_file: Path) -> None:
    sink = FileSink(sink_id="f1", path=str(tmp_sink_file), mode="append")
    result = await sink.send({"id": 1})
    assert result.ok is True
    assert result.details["mode"] == "append"
    text = tmp_sink_file.read_text(encoding="utf-8")
    assert '{"id":1}' in text


@pytest.mark.asyncio
async def test_append_str_payload_adds_newline(tmp_sink_file: Path) -> None:
    sink = FileSink(sink_id="f2", path=str(tmp_sink_file), mode="append")
    result = await sink.send("hello")
    assert result.ok is True
    text = tmp_sink_file.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "hello" in text


@pytest.mark.asyncio
async def test_write_mode_atomic_replace(tmp_sink_file: Path) -> None:
    sink = FileSink(sink_id="f3", path=str(tmp_sink_file), mode="write")
    result = await sink.send("first")
    assert result.ok is True
    assert tmp_sink_file.read_text(encoding="utf-8") == "first"
    result2 = await sink.send("second")
    assert result2.ok is True
    assert tmp_sink_file.read_text(encoding="utf-8") == "second"


@pytest.mark.asyncio
async def test_ensure_dir_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "dir" / "out.txt"
    sink = FileSink(sink_id="f4", path=str(target), ensure_dir=True)
    result = await sink.send("x")
    assert result.ok is True
    assert target.exists()


@pytest.mark.asyncio
async def test_ensure_dir_false_does_not_create_parent(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "out.txt"
    sink = FileSink(sink_id="f5", path=str(target), ensure_dir=False)
    result = await sink.send("x")
    assert result.ok is False
    assert (
        "No such file" in result.details["error"]
        or "cannot find the path" in result.details["error"].lower()
    )


@pytest.mark.asyncio
async def test_send_handles_write_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.txt"
    sink = FileSink(sink_id="f6", path=str(target), mode="write")

    def _boom(_target: Path, _text: str) -> int:
        raise PermissionError("denied")

    monkeypatch.setattr(sink, "_write_sync", _boom)
    result = await sink.send("x")
    assert result.ok is False
    assert "denied" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true_when_writable(tmp_path: Path) -> None:
    sink = FileSink(sink_id="f7", path=str(tmp_path / "out.txt"), ensure_dir=True)
    assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_false_when_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = FileSink(sink_id="f8", path=str(tmp_path / "out.txt"), ensure_dir=False)
    monkeypatch.setattr(Path, "is_dir", lambda self: False)
    assert await sink.health() is False
