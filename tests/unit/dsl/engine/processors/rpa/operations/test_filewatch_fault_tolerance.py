"""ADR-0368 — ``FileWatchProcessor`` (RPA): ранний выход, дедуп, ошибки.

До фикса:
* процессор всегда ждал полный ``timeout`` (файл @0.3s → возврат 5.01s);
* один и тот же путь попадал в результат дважды (create + modify);
* несуществующая папка → необработанный ``FileNotFoundError`` из watchdog.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.rpa.operations.filewatchprocessor import (
    FileWatchProcessor,
    _ChangeCollector,
)


def _exchange() -> Exchange[object]:
    return Exchange(in_message=Message(body={}))


@pytest.mark.unit
class TestFileWatchFaultTolerance:
    """FileWatchProcessor: отказоустойчивость RPA-watch."""

    async def test_returns_early_on_first_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
        processor = FileWatchProcessor(
            directory=str(tmp_path), pattern="*.txt", timeout=5.0
        )
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()

        async def _create_file() -> None:
            await asyncio.sleep(0.5)
            (tmp_path / "new.txt").write_text("data")

        creator = asyncio.create_task(_create_file())
        started = time.monotonic()
        await processor.process(exchange, ExecutionContext())
        elapsed = time.monotonic() - started
        await creator

        assert elapsed < 3.0, "watcher ждёт полный timeout вместо раннего выхода"
        assert exchange.status != ExchangeStatus.failed
        changes = exchange.in_message.body.get("changes", [])
        assert any("new.txt" in str(path) for path in changes), changes
        assert len(changes) == len(set(changes)), "дубли путей в результате"

    def test_change_collector_deduplicates_paths(self) -> None:
        collector = _ChangeCollector("*.txt")
        collector.add("/tmp/dir/report.txt")
        collector.add("/tmp/dir/report.txt")
        assert collector.changes == ["/tmp/dir/report.txt"]

    async def test_missing_directory_fails_exchange(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
        processor = FileWatchProcessor(
            directory=str(tmp_path / "missing"), pattern="*.txt", timeout=1.0
        )
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()

        await processor.process(exchange, ExecutionContext())

        assert exchange.status == ExchangeStatus.failed
        assert "exist" in (exchange.error or "").lower(), exchange.error

    async def test_observer_start_failure_fails_exchange(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
        processor = FileWatchProcessor(
            directory=str(tmp_path), pattern="*.txt", timeout=1.0
        )
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()

        class _BrokenObserver:
            def __init__(self) -> None:
                pass

            def schedule(self, *args: object, **kwargs: object) -> None:
                return None

            def start(self) -> None:
                raise OSError("observer start failed")

            def stop(self) -> None:
                return None

            def join(self, timeout: float | None = None) -> None:
                return None

        with patch("watchdog.observers.Observer", new=_BrokenObserver):
            await processor.process(exchange, ExecutionContext())

        assert exchange.status == ExchangeStatus.failed
        assert "observer" in (exchange.error or "").lower(), exchange.error
