"""Wave 2.5 (техдолг): интеграция structlog pipeline ↔ ``SinkRouter``.

Покрытие:

1. ``init_log_sinks`` поднимает router c корректным набором sink-ов.
2. structlog log → ``route_to_sinks`` → mock-sink получает event_dict
   с финальными обогащёнными полями (event/level/timestamp).
3. ``route_to_sinks`` — no-op до явной инициализации router'а
   (pre-init контекст не должен порождать sink-и и потоки).
4. ``shutdown_log_sinks`` корректно вызывает ``flush`` + ``close``
   на всех sink-ах и обнуляет глобальный router.
5. Повторный ``init_log_sinks`` идемпотентен — заменяет sink-и без падения.
6. Падение одного sink в pipeline не ломает остальные (изоляция).
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from src.backend.core.config.profile import AppProfileChoices
from src.backend.core.interfaces.log_sink import LogSink
from src.backend.infrastructure.logging import (
    init_log_sinks,
    is_router_configured,
    reset_router,
    shutdown_log_sinks,
)
from src.backend.infrastructure.logging.backends import ConsoleJsonLogSink
from src.backend.infrastructure.logging.router import (
    configure_router,
    get_router,
    route_to_sinks,
)


# ---------------------------------------------------------------------- helpers
class _CollectingSink(LogSink):
    """Тестовый sink: собирает все ``write`` в список + считает flush/close.

    Опционально может быть unhealthy или бросать исключения в ``write``,
    что нужно для проверки изоляции отказов.
    """

    def __init__(
        self,
        name: str = "collecting",
        *,
        fail: bool = False,
        healthy: bool = True,
    ) -> None:
        self.name = name
        self.is_healthy = healthy
        self._fail = fail
        self.records: list[dict[str, Any]] = []
        self.flushed = 0
        self.closed = 0

    async def write(self, record: dict[str, Any]) -> None:
        if self._fail:
            raise RuntimeError("simulated write failure")
        self.records.append(record)

    async def flush(self) -> None:
        self.flushed += 1

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def _reset_router_between_tests() -> Any:
    """Гарантирует чистый глобальный router между тестами."""
    reset_router()
    yield
    reset_router()


# ---------------------------------------------------------------------- tests
def test_init_log_sinks_configures_router_for_dev_light() -> None:
    """``init_log_sinks(dev_light)`` поднимает router с одним ConsoleJson-sink."""
    assert is_router_configured() is False
    init_log_sinks(AppProfileChoices.dev_light)
    assert is_router_configured() is True

    router = get_router()
    sinks = router.sinks
    assert len(sinks) == 1
    assert isinstance(sinks[0], ConsoleJsonLogSink)


def test_route_to_sinks_is_noop_before_init() -> None:
    """До явной инициализации processor НЕ создаёт router и НЕ спавнит потоки."""
    assert is_router_configured() is False

    initial_threads = {t.ident for t in threading.enumerate()}
    event = {"event": "pre_init", "level": "info"}

    # Должен пройти без ошибок, без создания router'а и без spawn'а потоков.
    result = route_to_sinks(None, "info", event)

    assert result is event
    assert is_router_configured() is False
    # log-sink-dispatch потоки НЕ должны были появиться
    new_threads = {t.ident for t in threading.enumerate()}
    extra = new_threads - initial_threads
    extra_named = [
        t.name for t in threading.enumerate() if t.ident in extra
    ]
    assert "log-sink-dispatch" not in extra_named


@pytest.mark.asyncio
async def test_route_to_sinks_dispatches_in_running_loop() -> None:
    """В running event loop processor отправляет event_dict в sink через ``create_task``."""
    sink = _CollectingSink("rec")
    configure_router([sink])

    event = {
        "event": "hello",
        "level": "info",
        "timestamp": "2026-05-01T00:00:00Z",
        "answer": 42,
    }
    route_to_sinks(None, "info", dict(event))

    # дать loop'у обработать поставленную задачу
    for _ in range(10):
        await asyncio.sleep(0)
        if sink.records:
            break
    assert sink.records == [event]


@pytest.mark.asyncio
async def test_shutdown_log_sinks_flushes_and_closes_then_resets() -> None:
    """``shutdown_log_sinks`` вызывает ``flush`` + ``close`` и обнуляет router."""
    a = _CollectingSink("a")
    b = _CollectingSink("b")
    configure_router([a, b])
    assert is_router_configured() is True

    await shutdown_log_sinks()

    assert a.flushed == 1 and a.closed == 1
    assert b.flushed == 1 and b.closed == 1
    assert is_router_configured() is False


@pytest.mark.asyncio
async def test_shutdown_log_sinks_is_noop_when_not_configured() -> None:
    """``shutdown_log_sinks`` без активного router'а — тихий no-op."""
    assert is_router_configured() is False
    # Не должен падать
    await shutdown_log_sinks()
    assert is_router_configured() is False


def test_init_log_sinks_idempotent_replaces_sinks() -> None:
    """Повторный ``init_log_sinks`` заменяет набор sink-ов без падения."""
    init_log_sinks(AppProfileChoices.dev_light)
    first_sinks = get_router().sinks
    assert len(first_sinks) == 1

    # повторный вызов с другим профилем — заменит набор
    init_log_sinks(AppProfileChoices.dev_light)
    second_sinks = get_router().sinks
    assert len(second_sinks) == 1
    # router тот же, но sinks-список пересоздан
    assert second_sinks is not first_sinks


@pytest.mark.asyncio
async def test_route_to_sinks_isolates_failing_sink_from_others() -> None:
    """Отказ одного sink в pipeline не должен препятствовать доставке в остальные."""
    bad = _CollectingSink("bad", fail=True)
    good = _CollectingSink("good")
    configure_router([bad, good])

    route_to_sinks(None, "info", {"event": "fan_out"})

    for _ in range(10):
        await asyncio.sleep(0)
        if good.records:
            break

    assert good.records == [{"event": "fan_out"}]
    # bad sink упал внутри write — но это поглощено gather(return_exceptions=True)


@pytest.mark.asyncio
async def test_structlog_pipeline_dispatches_to_sink() -> None:
    """End-to-end: structlog.get_logger().info(...) доставляет event в sink.

    Подключаем минимальный structlog-pipeline (без stdlib-bridge), чтобы
    проверить именно интеграцию ``route_to_sinks`` с ``structlog.configure``.
    """
    import structlog

    sink = _CollectingSink("e2e")
    configure_router([sink])

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            route_to_sinks,  # type: ignore[list-item]
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=False,
    )

    try:
        logger = structlog.get_logger("test_pipeline")
        logger.info("integration_event", answer=42)

        for _ in range(20):
            await asyncio.sleep(0)
            if sink.records:
                break

        assert len(sink.records) == 1
        record = sink.records[0]
        assert record["event"] == "integration_event"
        assert record["answer"] == 42
        assert record["level"] == "info"
        assert "timestamp" in record
    finally:
        structlog.reset_defaults()
