"""S178 #2: тесты что file_watch.py использует asyncio.to_thread (не блокирует event loop).

Проверяем что ``FileWatchProcessor.process()`` не делает blocking I/O
напрямую — оборачивает в ``asyncio.to_thread``.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors import file_watch as fw_mod
from src.backend.dsl.engine.processors.file_watch import FileWatchProcessor


def _make_exchange() -> Exchange:
    return Exchange(
        in_message=Message(body=None, headers={}), properties={}
    )


class TestFileWatchUsesToThread:
    """S178 #2: file_watch.process() оборачивает I/O в asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_isdir_called_via_to_thread(self) -> None:
        """``os.path.isdir`` обёрнут в ``asyncio.to_thread``."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "a.txt"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*.txt")
            exchange = _make_exchange()

            # Patch ``asyncio.to_thread`` чтобы spy'ить вызовы.
            original_to_thread = asyncio.to_thread

            call_args: list[tuple] = []

            async def spy_to_thread(func, *args, **kwargs):
                call_args.append((func, args, kwargs))
                return await original_to_thread(func, *args, **kwargs)

            with patch.object(fw_mod.asyncio, "to_thread", side_effect=spy_to_thread):
                await proc.process(exchange, MagicMock())

            # asyncio.to_thread вызывался хотя бы раз.
            assert len(call_args) >= 2, (
                f"Expected asyncio.to_thread calls, got {len(call_args)}"
            )
            # Первый вызов — isdir().
            first_func = call_args[0][0]
            assert first_func is os.path.isdir, (
                f"First to_thread call should wrap isdir, got {first_func}"
            )
            # Результат — 1 файл в exchange.
            assert len(exchange.properties["matched_files"]) == 1

    @pytest.mark.asyncio
    async def test_listdir_called_via_to_thread(self) -> None:
        """При ``include_subdirs=False`` — ``_list_matching_files`` в to_thread."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "b.csv"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*.csv")
            exchange = _make_exchange()

            original_to_thread = asyncio.to_thread

            call_targets: list[object] = []

            async def spy_to_thread(func, *args, **kwargs):
                call_targets.append(func)
                return await original_to_thread(func, *args, **kwargs)

            with patch.object(fw_mod.asyncio, "to_thread", side_effect=spy_to_thread):
                await proc.process(exchange, MagicMock())

            # Один из вызовов должен быть _list_matching_files.
            assert fw_mod._list_matching_files in call_targets, (
                f"Expected _list_matching_files in to_thread calls, got {call_targets}"
            )

    @pytest.mark.asyncio
    async def test_walk_called_via_to_thread(self) -> None:
        """При ``include_subdirs=True`` — ``_walk_matching_files`` в to_thread."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "sub")
            os.makedirs(sub)
            open(os.path.join(sub, "deep.csv"), "w").close()

            proc = FileWatchProcessor(
                directory=tmpdir, pattern="*.csv", include_subdirs=True
            )
            exchange = _make_exchange()

            original_to_thread = asyncio.to_thread

            call_targets: list[object] = []

            async def spy_to_thread(func, *args, **kwargs):
                call_targets.append(func)
                return await original_to_thread(func, *args, **kwargs)

            with patch.object(fw_mod.asyncio, "to_thread", side_effect=spy_to_thread):
                await proc.process(exchange, MagicMock())

            # Один из вызовов должен быть _walk_matching_files.
            assert fw_mod._walk_matching_files in call_targets, (
                f"Expected _walk_matching_files in to_thread calls, got {call_targets}"
            )

    @pytest.mark.asyncio
    async def test_oserror_in_thread_returns_exchange_fail(self) -> None:
        """OSError внутри ``to_thread`` → ``exchange.fail`` (не propagate)."""
        proc = FileWatchProcessor(directory="/nonexistent/path")
        exchange = _make_exchange()

        await proc.process(exchange, MagicMock())

        # exchange должен быть failed.
        assert exchange.status == ExchangeStatus.failed

    @pytest.mark.asyncio
    async def test_sync_helpers_return_tuples(self) -> None:
        """``_list_matching_files`` и ``_walk_matching_files`` возвращают (path, stat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "test.txt")
            open(target, "w").close()

            listed = fw_mod._list_matching_files(tmpdir, "*.txt")
            assert len(listed) == 1
            path, stat = listed[0]
            assert path == target
            assert stat.st_size == 0

            walked = fw_mod._walk_matching_files(tmpdir, "*.txt")
            assert len(walked) == 1
            path2, stat2 = walked[0]
            assert path2 == target
            assert stat2.st_size == 0
