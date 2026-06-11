"""Unit-тесты для FileWatchProcessor (Sprint 36).

Тестирует:
- сканирование директории с фильтрацией по паттерну
- рекурсивное сканирование
- обработку несуществующей директории
"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.file_watch import FileWatchProcessor


def _make_exchange(properties: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=None, headers={}), properties=properties or {})


class TestFileWatchProcessor:
    """Тесты для FileWatchProcessor."""

    @pytest.mark.asyncio
    async def test_file_watch_matches_pattern(self) -> None:
        """Фильтрация файлов по паттерну."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "a.csv"), "w").close()
            open(os.path.join(tmpdir, "b.txt"), "w").close()
            open(os.path.join(tmpdir, "c.csv"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*.csv")
            exchange = _make_exchange()
            await proc.process(exchange, MagicMock())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 2
            names = {f["name"] for f in result}
            assert names == {"a.csv", "c.csv"}

    @pytest.mark.asyncio
    async def test_file_watch_all_files(self) -> None:
        """Паттерн * возвращает все файлы."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "x"), "w").close()
            open(os.path.join(tmpdir, "y"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*")
            exchange = _make_exchange()
            await proc.process(exchange, MagicMock())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_file_watch_subdirs(self) -> None:
        """Рекурсивное сканирование."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "sub")
            os.makedirs(sub)
            open(os.path.join(sub, "nested.csv"), "w").close()

            proc = FileWatchProcessor(
                directory=tmpdir, pattern="*.csv", include_subdirs=True
            )
            exchange = _make_exchange()
            await proc.process(exchange, MagicMock())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 1
            assert result[0]["name"] == "nested.csv"

    @pytest.mark.asyncio
    async def test_file_watch_nonexistent_directory(self) -> None:
        """Несуществующая директория — exchange.fail."""
        proc = FileWatchProcessor(directory="/nonexistent/path")
        exchange = _make_exchange()
        await proc.process(exchange, MagicMock())

        assert exchange.status == ExchangeStatus.failed
        assert "does not exist" in (exchange.error or "")

    @pytest.mark.asyncio
    async def test_file_watch_directory_from_property(self) -> None:
        """Директория из exchange property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "file"), "w").close()

            proc = FileWatchProcessor(directory="/wrong/path")
            exchange = _make_exchange(properties={"watch_directory": tmpdir})
            await proc.process(exchange, MagicMock())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 1

    def test_file_watch_to_spec(self) -> None:
        """Сериализация в spec."""
        proc = FileWatchProcessor(
            directory="/data", pattern="*.csv", include_subdirs=True
        )
        spec = proc.to_spec()
        assert spec == {
            "file_watch": {
                "directory": "/data",
                "pattern": "*.csv",
                "result_property": "matched_files",
                "include_subdirs": True,
            }
        }
