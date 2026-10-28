"""Wave 13 Q2 — декларация ``log.required_fields`` должна исполняться.

Конфиг (``config_profiles/base.yml`` → ``log.required_fields``) объявляет
обязательные поля записи: ``environment``, ``hostname``, ``user_id``,
``action``. Legacy-путь (``external_apis.logging_service.SafeFormatter``)
гарантировал их наличие, а structlog-пайплайн — нет: ``user_id``/``action``
просто отсутствовали в ``event_dict``. Конфиг врёт.

Тест проверяет сквозной путь реального пайплайна:
``configure_logging()`` → structlog → processor → ``SinkRouter`` → sink.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest

from src.backend.core.config.profile import AppProfileChoices
from src.backend.core.interfaces.log_sink import LogSink
from src.backend.core.logging import configure_logging, get_logger
from src.backend.infrastructure.logging import factory
from src.backend.infrastructure.logging.router import configure_router, reset_router

REQUIRED_FIELDS = ["environment", "hostname", "user_id", "action"]


class _CaptureSink(LogSink):
    """Sink-заглушка: складывает полученные ``event_dict`` в список."""

    name = "capture"
    is_healthy = True

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def write(self, record: dict[str, Any]) -> None:
        """Сохраняет запись для последующих assert'ов."""
        self.records.append(record)

    async def flush(self) -> None:
        """Буферов нет — no-op."""

    async def close(self) -> None:
        """Ресурсов нет — no-op."""


@pytest.fixture()
def capture_sink() -> Iterator[_CaptureSink]:
    """Structlog-бэкенд с ``required_fields`` + sink для захвата записей."""
    reset_router()
    factory._backend = None
    sink = _CaptureSink()
    # dev_light → без batching-роутера (dispatch идёт напрямую в sink).
    configure_router([sink], profile=AppProfileChoices.dev_light)
    configure_logging(
        backend="structlog",
        level="INFO",
        environment="test-env",
        required_fields=list(REQUIRED_FIELDS),
    )
    yield sink
    factory._backend = None
    reset_router()


def _wait_for_record(sink: _CaptureSink, timeout: float = 2.0) -> dict[str, Any]:
    """Дожидается доставки event_dict в sink (dispatch идёт в потоке)."""
    deadline = time.monotonic() + timeout
    while not sink.records and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sink.records, "structlog-event не дошёл до sink"
    return sink.records[-1]


def test_missing_required_fields_are_filled(capture_sink: _CaptureSink) -> None:
    """В записи без ``user_id``/``action`` все обязательные поля присутствуют."""
    logger = get_logger("required-fields")
    logger.info("order.created", order_id=42)

    record = _wait_for_record(capture_sink)

    for field in REQUIRED_FIELDS:
        assert field in record, f"обязательное поле {field!r} отсутствует в записи"
    assert record["user_id"] == "unknown"
    assert record["action"] == "unknown"
    assert record["environment"] == "test-env"
    assert record["hostname"]


def test_explicit_required_fields_are_not_overwritten(
    capture_sink: _CaptureSink,
) -> None:
    """Явно переданные значения не затираются дефолтом ``"unknown"``."""
    logger = get_logger("required-fields")
    logger.info("user.login", user_id="alice", action="login")

    record = _wait_for_record(capture_sink)

    assert record["user_id"] == "alice"
    assert record["action"] == "login"


def test_init_application_logging_passes_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings-driven init прокидывает ``required_fields`` в бэкенд."""
    from src.backend.core.config.settings import settings

    captured: dict[str, Any] = {}

    def _fake_configure_logging(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(factory, "configure_logging", _fake_configure_logging)
    monkeypatch.setattr(factory, "init_log_sinks", lambda *a, **kw: None)

    factory.init_application_logging()

    assert captured.get("required_fields") == settings.logging.required_fields
