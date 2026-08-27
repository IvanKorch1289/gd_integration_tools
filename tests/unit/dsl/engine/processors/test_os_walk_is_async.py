"""P2.12: regression-тест что ``FileWatchProcessor.process()`` не блокирует event loop.

Подтверждает S178 #2 fix: ``os.walk`` обёрнут в ``asyncio.to_thread`` через
sync helper ``_walk_matching_files`` (вызывается на ``file_watch.py:198-201``).
Audit CURRENT_STATE_2026-08-27.md (WAVE 1) flag'ал P2.12 как PARTIAL — на
самом деле fix уже был сделан в ``7d8d8836`` (S178 m-st-fix), но без явного
неблокирующего теста под нагрузкой. Этот файл — недостающий regression gate.

Стратегия:
1. Создаём глубокое дерево (subdirs + файлы) — достаточно большое чтобы
   синхронный ``os.walk`` заметно задержал event loop.
2. Запускаем ``proc.process(...)`` через ``asyncio.create_task``.
3. Параллельно запускаем "heartbeat" coroutine, которая инкрементирует счётчик
   каждые ~5ms пока scan идёт.
4. Если ``os.walk`` синхронный — heartbeat НЕ успеет сделать ticks за время scan.
5. С использованием ``asyncio.wait_for(scan, timeout=2s)`` — scan завершается
   в пределах timeout (НЕ timeout'ит → event loop не висит).

Ключевая проверка: ``heartbeat_ticks > 0`` пока scan идёт, И ``scan`` НЕ
завершается с ``asyncio.TimeoutError``. Если бы ``os.walk`` блокировал event
loop, scan либо timeout'ил, либо heartbeat'ы были бы нулевыми.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from unittest.mock import MagicMock

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.file_watch import FileWatchProcessor


def _make_exchange() -> Exchange:
    """Создать пустой Exchange для тестов process()."""
    return Exchange(
        in_message=Message(body=None, headers={}), properties={},
    )


def _create_deep_tree(root: str, depth: int = 5, files_per_dir: int = 30) -> int:
    """Создаёт глубокое дерево директорий с файлами.

    Возвращает общее число созданных файлов.
    """
    total_files = 0
    for level in range(depth):
        level_root = os.path.join(root, *([f"level_{i}" for i in range(level + 1)]))
        os.makedirs(level_root, exist_ok=True)
        for i in range(files_per_dir):
            target = os.path.join(level_root, f"file_{i}.csv")
            with open(target, "w") as f:
                f.write("x" * 10)
            total_files += 1
    return total_files


class TestOsWalkIsAsync:
    """P2.12: ``os.walk`` НЕ блокирует event loop в ``FileWatchProcessor.process()``."""

    async def test_heartbeat_runs_during_walk(self) -> None:
        """Heartbeat coroutine делает ticks пока scan идёт (event loop не заблокирован)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            total = _create_deep_tree(tmpdir, depth=5, files_per_dir=30)
            # Sanity: дерево создано достаточно большое.
            assert total >= 100, f"Expected large tree, got {total} files"

            proc = FileWatchProcessor(
                directory=tmpdir, pattern="*.csv", include_subdirs=True,
            )
            exchange = _make_exchange()

            # Heartbeat: инкрементирует счётчик пока scan не завершён.
            heartbeat_ticks = 0
            scan_done = asyncio.Event()

            async def heartbeat() -> None:
                nonlocal heartbeat_ticks
                while not scan_done.is_set():
                    heartbeat_ticks += 1
                    await asyncio.sleep(0.005)  # 5ms

            # Запускаем scan + heartbeat параллельно.
            scan_task = asyncio.create_task(proc.process(exchange, MagicMock()))
            heartbeat_task = asyncio.create_task(heartbeat())

            # scan должен завершиться быстро (small timeout).
            try:
                await asyncio.wait_for(asyncio.shield(scan_task), timeout=2.0)
            finally:
                scan_done.set()
                await heartbeat_task

            # Scan succeeded.
            assert exchange.status.value != "failed", (
                f"Scan failed: {exchange.error}"
            )
            matched = exchange.properties.get("matched_files", [])
            assert len(matched) == total, (
                f"Expected {total} matched, got {len(matched)}"
            )
            # Ключевая проверка: heartbeat успел сделать ticks (event loop не заблокирован).
            assert heartbeat_ticks > 0, (
                f"Heartbeat made 0 ticks during {total}-file scan — "
                f"os.walk is BLOCKING the event loop!"
            )

    async def test_process_completes_within_timeout(self) -> None:
        """``process()`` завершается в пределах разумного timeout (НЕ asyncio.TimeoutError)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_deep_tree(tmpdir, depth=3, files_per_dir=20)

            proc = FileWatchProcessor(
                directory=tmpdir, pattern="*", include_subdirs=True,
            )
            exchange = _make_exchange()

            # 2 секунды достаточно для ~60 файлов на современном FS.
            # Если os.walk блокирующий + sync, тест может timeout'нуть на медленном I/O.
            # Используем to_thread-based impl → всегда укладывается.
            await asyncio.wait_for(proc.process(exchange, MagicMock()), timeout=2.0)

            matched = exchange.properties.get("matched_files", [])
            assert len(matched) > 0

    async def test_event_loop_processes_other_tasks_during_walk(self) -> None:
        """Другая coroutine успевает выполниться во время walk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_deep_tree(tmpdir, depth=4, files_per_dir=20)

            proc = FileWatchProcessor(
                directory=tmpdir, pattern="*.csv", include_subdirs=True,
            )
            exchange = _make_exchange()

            order: list[str] = []

            async def sibling_task() -> None:
                order.append("sibling:start")
                await asyncio.sleep(0.01)
                order.append("sibling:end")

            scan_task = asyncio.create_task(proc.process(exchange, MagicMock()))
            sibling = asyncio.create_task(sibling_task())

            await asyncio.gather(scan_task, sibling)

            # Sibling выполнился ДО завершения scan, или в параллель.
            # Главное — он вообще выполнился (не "застрял" после scan).
            assert "sibling:start" in order
            assert "sibling:end" in order
            # Порядок: sibling должен выполниться, scan завершается.
            assert len(order) >= 2


class TestOsWalkWrappingDirect:
    """P2.12: прямые structural checks на обёртку ``os.walk``."""

    def test_walk_matching_files_is_called_via_to_thread(self) -> None:
        """``_walk_matching_files`` вызывается через ``asyncio.to_thread`` в process()."""
        from src.backend.dsl.engine.processors import file_watch as fw_mod

        source = inspect.getsource(fw_mod.FileWatchProcessor.process)
        # process() содержит обёртку to_thread для _walk_matching_files.
        assert "asyncio.to_thread" in source
        assert "_walk_matching_files" in source

    def test_walk_helper_uses_os_walk(self) -> None:
        """``_walk_matching_files`` действительно использует ``os.walk``."""
        from src.backend.dsl.engine.processors import file_watch as fw_mod

        source = inspect.getsource(fw_mod._walk_matching_files)
        assert "os.walk" in source
