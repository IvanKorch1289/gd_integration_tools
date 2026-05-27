"""K7 W4 — smoke-тесты FileWatcherSource.

Покрывают:
* эмиссию события ``added`` при создании файла;
* эмиссию события ``modified`` при изменении содержимого;
* эмиссию события ``deleted`` при удалении файла;
* игнорирование вложенных файлов при ``recursive=False``.

Все тесты ограничены таймаутом 5 с, используют ``tmp_path`` pytest-фикстуру.
watchfiles и pytest-timeout проверяются через importorskip.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

# Пропуск всего модуля, если watchfiles не установлен
watchfiles = pytest.importorskip("watchfiles")

from src.backend.infrastructure.sources.file_watcher import FileEvent, FileWatcherSource  # noqa: E402


async def _collect_one(source: FileWatcherSource, timeout: float = 3.0) -> FileEvent:
    """Собрать ровно одно событие из stream() с таймаутом.

    Args:
        source: Источник событий.
        timeout: Максимальное время ожидания в секундах.

    Returns:
        Первое полученное событие.

    Raises:
        TimeoutError: Если за ``timeout`` секунд событие не поступило.
    """
    async def _inner() -> FileEvent:
        async for event in source.stream():
            return event
        raise RuntimeError("stream() завершился без события")  # noqa: TRY301

    return await asyncio.wait_for(_inner(), timeout=timeout)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_emits_added(tmp_path: Path) -> None:
    """Создание файла порождает событие change_type='added'."""
    source = FileWatcherSource("test_emits_added", tmp_path, recursive=False, debounce=0.05)
    target = tmp_path / "new_file.txt"

    async def _write_after_delay() -> None:
        await asyncio.sleep(0.1)
        target.write_text("hello")

    write_task = asyncio.create_task(_write_after_delay())
    try:
        event = await _collect_one(source)
    finally:
        write_task.cancel()
        try:
            await write_task
        except (asyncio.CancelledError, Exception):
            pass

    assert event.change_type == "added"
    assert event.path == target
    assert event.timestamp > 0


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_emits_modified(tmp_path: Path) -> None:
    """Изменение содержимого существующего файла порождает событие 'modified'."""
    target = tmp_path / "existing.txt"
    target.write_text("initial")

    source = FileWatcherSource("test_emits_modified", tmp_path, recursive=False, debounce=0.05)

    async def _modify_after_delay() -> None:
        await asyncio.sleep(0.1)
        target.write_text("changed content")

    modify_task = asyncio.create_task(_modify_after_delay())
    try:
        event = await _collect_one(source)
    finally:
        modify_task.cancel()
        try:
            await modify_task
        except (asyncio.CancelledError, Exception):
            pass

    assert event.change_type in ("modified", "added")  # watchfiles может emit added при замене
    assert event.path == target


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_emits_deleted(tmp_path: Path) -> None:
    """Удаление файла порождает событие change_type='deleted'."""
    target = tmp_path / "to_delete.txt"
    target.write_text("bye")

    source = FileWatcherSource("test_emits_deleted", tmp_path, recursive=False, debounce=0.05)

    async def _delete_after_delay() -> None:
        await asyncio.sleep(0.1)
        target.unlink()

    delete_task = asyncio.create_task(_delete_after_delay())
    try:
        event = await _collect_one(source)
    finally:
        delete_task.cancel()
        try:
            await delete_task
        except (asyncio.CancelledError, Exception):
            pass

    assert event.change_type == "deleted"
    assert event.path == target


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_respects_recursive_false(tmp_path: Path) -> None:
    """При recursive=False события из вложенных директорий не поступают."""
    sub = tmp_path / "subdir"
    sub.mkdir()
    nested_file = sub / "nested.txt"
    top_file = tmp_path / "top.txt"

    source = FileWatcherSource("test_recursive_false", tmp_path, recursive=False, debounce=0.05)

    events: list[FileEvent] = []

    async def _collect_for(seconds: float) -> None:
        """Собирать события в течение ``seconds`` секунд."""
        try:
            async with asyncio.timeout(seconds):
                async for event in source.stream():
                    events.append(event)
        except TimeoutError:
            pass

    async def _make_changes() -> None:
        await asyncio.sleep(0.1)
        nested_file.write_text("nested")  # не должно попасть в события
        await asyncio.sleep(0.1)
        top_file.write_text("top")  # должно попасть

    collect_task = asyncio.create_task(_collect_for(1.5))
    change_task = asyncio.create_task(_make_changes())

    await asyncio.gather(collect_task, change_task, return_exceptions=True)

    # При recursive=False вложенные файлы не отслеживаются
    nested_events = [e for e in events if nested_file in (e.path,)]
    assert not nested_events, f"Неожиданные события из поддиректории: {nested_events}"

    # Хотя бы одно событие от top_file должно быть (но watchfiles может не всегда поймать)
    top_events = [e for e in events if e.path == top_file]
    assert top_events, f"Ожидалось событие для {top_file}, получено: {events}"
