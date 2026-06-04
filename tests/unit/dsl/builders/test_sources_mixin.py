"""Smoke-тесты SourcesMixin (K3 W5 — builder source-сахар).

Проверяют:
* Каждый classmethod возвращает корректный RouteBuilder.
* Поле ``source`` установлено с правильным префиксом и значением.
* ``route_id`` передаётся корректно.
* Source-классы НЕ инстанцируются в процессе теста — используются mock'и
  через ``unittest.mock.patch``.
"""
# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.backend.dsl.builders.sources_mixin import SourcesMixin

# ─── Вспомогательный RouteBuilder-stub ────────────────────────────────────────


class _FakeRouteBuilder(SourcesMixin):
    """Минимальный stub RouteBuilder для тестирования SourcesMixin.

    Реализует только необходимый интерфейс: хранит ``route_id`` и ``source``.
    Использует ``__new__`` + ``__init__`` вместо dataclass для совместимости
    с ``object.__setattr__`` в SourcesMixin.
    """

    def __init__(self, route_id: str, source: str | None = None) -> None:
        self.route_id = route_id
        self.source = source


# ─── test_from_kafka_returns_route_builder ────────────────────────────────────


def test_from_kafka_returns_route_builder() -> None:
    """from_kafka создаёт RouteBuilder с source=kafka:<topic>."""
    mock_mq_module = MagicMock()
    mock_mq_source = MagicMock()
    mock_mq_module.MQSource.return_value = mock_mq_source

    with patch.dict(
        "sys.modules", {"src.backend.infrastructure.sources.mq": mock_mq_module}
    ):
        builder = _FakeRouteBuilder.from_kafka(
            "payments.stream",
            topic="payments",
            bootstrap_servers="kafka:9092",
            group_id="payments-group",
        )

    assert isinstance(builder, _FakeRouteBuilder)
    assert builder.route_id == "payments.stream"
    assert builder.source == "kafka:payments"
    # Проверяем что MQSource был вызван с правильным transport
    mock_mq_module.MQSource.assert_called_once()
    call_kwargs = mock_mq_module.MQSource.call_args.kwargs
    assert call_kwargs["transport"] == "kafka"
    assert call_kwargs["topic"] == "payments"


# ─── test_from_rabbit_returns_route_builder ───────────────────────────────────


def test_from_rabbit_returns_route_builder() -> None:
    """from_rabbit создаёт RouteBuilder с source=rabbitmq:<queue>."""
    mock_mq_module = MagicMock()
    mock_mq_source = MagicMock()
    mock_mq_module.MQSource.return_value = mock_mq_source

    with patch.dict(
        "sys.modules", {"src.backend.infrastructure.sources.mq": mock_mq_module}
    ):
        builder = _FakeRouteBuilder.from_rabbit(
            "notifications.consumer",
            queue="notifications",
            url="amqp://guest:guest@rabbitmq/",
        )

    assert isinstance(builder, _FakeRouteBuilder)
    assert builder.route_id == "notifications.consumer"
    assert builder.source == "rabbitmq:notifications"
    call_kwargs = mock_mq_module.MQSource.call_args.kwargs
    assert call_kwargs["transport"] == "rabbitmq"
    assert call_kwargs["topic"] == "notifications"


# ─── test_from_redis_streams_returns_route_builder ───────────────────────────


def test_from_redis_streams_returns_route_builder() -> None:
    """from_redis_streams создаёт RouteBuilder с source=redis_streams:<stream>."""
    mock_mq_module = MagicMock()
    mock_mq_module.MQSource.return_value = MagicMock()

    with patch.dict(
        "sys.modules", {"src.backend.infrastructure.sources.mq": mock_mq_module}
    ):
        builder = _FakeRouteBuilder.from_redis_streams(
            "audit.trail",
            stream="audit:events",
            consumer_group="audit-consumers",
            connect_url="redis://redis:6379",
        )

    assert isinstance(builder, _FakeRouteBuilder)
    assert builder.route_id == "audit.trail"
    assert builder.source == "redis_streams:audit:events"
    call_kwargs = mock_mq_module.MQSource.call_args.kwargs
    assert call_kwargs["transport"] == "redis_streams"
    assert call_kwargs["topic"] == "audit:events"
    assert call_kwargs["group"] == "audit-consumers"


# ─── test_from_filewatcher_returns_route_builder ──────────────────────────────


def test_from_filewatcher_returns_route_builder() -> None:
    """from_filewatcher создаёт RouteBuilder с source=filewatcher:<path>."""
    mock_fw_module = MagicMock()
    mock_fw_source = MagicMock()
    mock_fw_module.FileWatcherSource.return_value = mock_fw_source

    with patch.dict(
        "sys.modules",
        {"src.backend.infrastructure.sources.file_watcher": mock_fw_module},
    ):
        builder = _FakeRouteBuilder.from_filewatcher(
            "config.hotreload", path="/etc/app/config", recursive=False
        )

    assert isinstance(builder, _FakeRouteBuilder)
    assert builder.route_id == "config.hotreload"
    assert builder.source == "filewatcher:/etc/app/config"
    mock_fw_module.FileWatcherSource.assert_called_once()
    call_kwargs = mock_fw_module.FileWatcherSource.call_args.kwargs
    assert call_kwargs["recursive"] is False
    assert call_kwargs["path"] == Path("/etc/app/config")


# ─── test_from_webhook_returns_route_builder ──────────────────────────────────


def test_from_webhook_returns_route_builder() -> None:
    """from_webhook создаёт RouteBuilder с source=webhook:<path>."""
    mock_wh_module = MagicMock()
    mock_wh_source = MagicMock()
    mock_wh_module.WebhookSource.return_value = mock_wh_source

    with patch.dict(
        "sys.modules", {"src.backend.infrastructure.sources.webhook": mock_wh_module}
    ):
        builder = _FakeRouteBuilder.from_webhook(
            "github.push", path="/webhooks/github", hmac_secret="test-secret"
        )

    assert isinstance(builder, _FakeRouteBuilder)
    assert builder.route_id == "github.push"
    assert builder.source == "webhook:/webhooks/github"
    mock_wh_module.WebhookSource.assert_called_once()
    call_kwargs = mock_wh_module.WebhookSource.call_args.kwargs
    assert call_kwargs["path"] == "/webhooks/github"
    assert call_kwargs["hmac_secret"] == "test-secret"


# ─── test_from_schedule_returns_route_builder ─────────────────────────────────


def test_from_schedule_returns_route_builder() -> None:
    """from_schedule создаёт RouteBuilder с source=schedule:<cron_expr>."""
    builder = _FakeRouteBuilder.from_schedule("reports.daily", cron_expr="0 9 * * 1-5")

    assert isinstance(builder, _FakeRouteBuilder)
    assert builder.route_id == "reports.daily"
    assert builder.source == "schedule:0 9 * * 1-5"
    # Проверяем что конфиг сохранён
    config = object.__getattribute__(builder, "_source_config")
    assert config["type"] == "schedule"
    assert config["cron_expr"] == "0 9 * * 1-5"
