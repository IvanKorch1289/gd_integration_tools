"""K7 W4 — smoke-тесты FileWatcherSource.

Покрывают:
* эмиссию события ``added`` при создании файла;
* эмиссию события ``modified`` при изменении содержимого;
* эмиссию события ``deleted`` при удалении файла;
* игнорирование вложенных файлов при ``recursive=False``;
* glob include/exclude фильтрацию;
* накопление событий в батчи по размеру и окну;
* наблюдение за несколькими путями.

Все тесты ограничены таймаутом 5 с, используют ``tmp_path`` pytest-фикстуру.
watchfiles и pytest-timeout проверяются через importorskip.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

# Пропуск всего модуля, если watchfiles не установлен
watchfiles = pytest.importorskip("watchfiles")

from src.backend.infrastructure.sources.file_watcher import (  # noqa: E402
    FileEvent,
    FileWatcherSource,
)


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


async def _collect_events(source: FileWatcherSource, seconds: float) -> list[FileEvent]:
    """Собрать события из ``stream()`` в течение ``seconds`` секунд."""
    events: list[FileEvent] = []
    try:
        async with asyncio.timeout(seconds):
            async for event in source.stream():
                events.append(event)
    except TimeoutError:
        pass
    return events


async def _fake_stream(events: list[FileEvent]) -> AsyncIterator[FileEvent]:
    """Синхронная подделка ``stream()`` для unit-тестов батчинга."""
    for event in events:
        yield event


async def _fake_stream_with_delay(
    events: list[FileEvent], delay: float
) -> AsyncIterator[FileEvent]:
    """Подделка ``stream()`` с паузой после первых двух событий."""
    for event in events[:2]:
        yield event
    await asyncio.sleep(delay)
    for event in events[2:]:
        yield event


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_emits_added(tmp_path: Path) -> None:
    """Создание файла порождает событие change_type='added'."""
    source = FileWatcherSource(
        "test_emits_added", tmp_path, recursive=False, debounce=0.05
    )
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

    source = FileWatcherSource(
        "test_emits_modified", tmp_path, recursive=False, debounce=0.05
    )

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

    assert event.change_type in (
        "modified",
        "added",
    )  # watchfiles может emit added при замене
    assert event.path == target


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_emits_deleted(tmp_path: Path) -> None:
    """Удаление файла порождает событие change_type='deleted'."""
    target = tmp_path / "to_delete.txt"
    target.write_text("bye")

    source = FileWatcherSource(
        "test_emits_deleted", tmp_path, recursive=False, debounce=0.05
    )

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

    source = FileWatcherSource(
        "test_recursive_false", tmp_path, recursive=False, debounce=0.05
    )

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


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_glob_include(tmp_path: Path) -> None:
    """``glob_include`` пропускает только файлы, соответствующие паттерну."""
    source = FileWatcherSource(
        "test_glob_include",
        tmp_path,
        recursive=False,
        debounce=0.05,
        glob_include="*.csv",
    )
    txt_file = tmp_path / "notes.txt"
    csv_file = tmp_path / "data.csv"

    async def _make_changes() -> None:
        await asyncio.sleep(0.1)
        txt_file.write_text("ignored")
        await asyncio.sleep(0.05)
        csv_file.write_text("csv data")

    collect_task = asyncio.create_task(_collect_events(source, 1.5))
    change_task = asyncio.create_task(_make_changes())
    await asyncio.gather(collect_task, change_task, return_exceptions=True)

    events = collect_task.result()
    assert all(e.path == csv_file for e in events), f"Ожидались только csv: {events}"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_glob_exclude(tmp_path: Path) -> None:
    """``glob_exclude`` отбрасывает файлы, соответствующие паттерну."""
    source = FileWatcherSource(
        "test_glob_exclude",
        tmp_path,
        recursive=False,
        debounce=0.05,
        glob_exclude="*.log",
    )
    log_file = tmp_path / "noise.log"
    txt_file = tmp_path / "notes.txt"

    async def _make_changes() -> None:
        await asyncio.sleep(0.1)
        log_file.write_text("ignored")
        await asyncio.sleep(0.05)
        txt_file.write_text("ok")

    collect_task = asyncio.create_task(_collect_events(source, 1.5))
    change_task = asyncio.create_task(_make_changes())
    await asyncio.gather(collect_task, change_task, return_exceptions=True)

    events = collect_task.result()
    assert not any(e.path == log_file for e in events), (
        f"log не должен попадать: {events}"
    )
    assert any(e.path == txt_file for e in events), f"txt должен попасть: {events}"


async def _multi_path_stream(events: list[FileEvent]) -> AsyncIterator[FileEvent]:
    """Подделка stream для теста нескольких путей."""
    for event in events:
        yield event


def test_file_watcher_multiple_paths(tmp_path: Path) -> None:
    """``FileWatcherSource`` может наблюдать сразу за несколькими путями."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    source = FileWatcherSource("test_multi_paths", paths=[dir_a, dir_b])
    assert len(source._paths) == 2
    assert dir_a.resolve() in source._paths
    assert dir_b.resolve() in source._paths


@pytest.mark.asyncio
async def test_file_watcher_batches_by_size(tmp_path: Path) -> None:
    """``_stream_batches`` группирует события до ``batch_size``."""
    events = [FileEvent(tmp_path / f"{i}.txt", "added") for i in range(5)]
    source = FileWatcherSource("test_batch_size", tmp_path, batch_size=2)
    source.stream = lambda: _fake_stream(events)

    batches = [batch async for batch in source._stream_batches()]
    sizes = [len(batch) for batch in batches]
    assert sizes == [2, 2, 1]


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_file_watcher_batches_by_window(tmp_path: Path) -> None:
    """``_stream_batches`` выдаёт батч по истечении ``batch_window``."""
    events = [FileEvent(tmp_path / f"{i}.txt", "added") for i in range(4)]
    source = FileWatcherSource("test_batch_window", tmp_path, batch_window=0.1)
    source.stream = lambda: _fake_stream_with_delay(events, 0.3)

    batches = [batch async for batch in source._stream_batches()]
    total = sum(len(batch) for batch in batches)
    assert total == 4
    assert len(batches) >= 2


@pytest.mark.asyncio
async def test_file_watcher_run_watch_emits_batches(tmp_path: Path) -> None:
    """``_run_watch`` эмитит батч как один ``SourceEvent`` со списком событий."""
    events = [FileEvent(tmp_path / f"{i}.txt", "added") for i in range(3)]
    source = FileWatcherSource("test_run_watch_batch", tmp_path, batch_size=10)
    source.stream = lambda: _fake_stream(events)

    from src.backend.core.interfaces.source import SourceEvent

    collected: list[SourceEvent] = []

    async def _on_event(event: SourceEvent) -> None:
        collected.append(event)

    source._on_event = _on_event
    await source._run_watch()

    assert len(collected) == 1
    payload = collected[0].payload
    assert payload["count"] == 3
    assert len(payload["events"]) == 3
    assert payload["events"][0]["path"] == str(events[0].path)
    assert payload["events"][0]["change_type"] == "added"
