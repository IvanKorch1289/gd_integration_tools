"""Regression-локи на wiring gap ``mq_trace_propagator`` (S-L7-5, Sprint 4 L10).

Назначение:
    Модуль ``infrastructure/observability/mq_trace_propagator.py`` —
    declared ready (S18 W7, ADR-0096), но wiring в Kafka/RabbitMQ/NATS
    producer/consumer отсутствует (carryover S19+, требует изменения 4+
    файлов в infrastructure/messaging/ — см. docstring модуля:42-43).

    KNOWN_ISSUES.md: ``S-L7-5 Кросс-сервисная trace_id propagation в
    Kafka/RabbitMQ headers отсутствует``.

Что лочат тесты:
    * Static-analysis: каждый файл messaging-слоя, который должен
      пробрасывать W3C TraceContext, НЕ должен импортировать
      ``inject_into_headers`` (current state).
    * Runtime: ``KafkaDLQWriter.write`` НЕ передаёт ``headers=`` в
      ``producer.send_and_wait`` (current state).
    * Runtime: ``RabbitDLQWriter.write`` НЕ инжектит W3C ``traceparent``
      в ``Message.headers`` (передаёт только envelope.trace_id).
    * Runtime: ``NATSDLQWriter.write`` НЕ инжектит W3C ``traceparent``
      (передаёт ``X-Trace`` envelope.trace_id).

Когда wiring состоится (следующий sprint, не Sprint 4):
    Эти тесты должны быть УДАЛЕНЫ вместе с wiring — они лочат ТЕКУЩЕЕ
    (отсутствующее) поведение. После wiring — НОВЫЕ тесты на
    положительный сценарий (round-trip через реальный брокер).

Все runtime-тесты мокают только ``producer.send_and_wait`` /
``exchange.publish`` / ``JetStream.publish``, без реальной сети.
Auth (``require_capability("dlq.write", ...)``) — bypass через
monkeypatch на уровне facade.
"""


from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ────────────────────── helpers ──────────────────────


def _read(path: Path) -> str:
    """Читает файл как UTF-8 (для статического анализа)."""
    return path.read_text(encoding="utf-8")


def _has_inject_import_or_call(source: str) -> bool:
    """AST-проверка: ``inject_into_headers`` используется в файле?

    Проверяем:
        1. ``from ...mq_trace_propagator import inject_into_headers``
        2. ``import ...mq_trace_propagator`` + атрибут ``inject_into_headers``
        3. Прямой вызов ``inject_into_headers(...)``
    """
    tree = ast.parse(source)

    # 1+2. Импорты.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.endswith("mq_trace_propagator"):
                for alias in node.names:
                    if alias.name in {
                        "inject_into_headers",
                        "extract_from_headers",
                    }:
                        return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("mq_trace_propagator"):
                    return True  # star-imports покрываем тоже

    # 3. Прямые вызовы.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {
                "inject_into_headers",
                "extract_from_headers",
            }:
                return True
            if isinstance(func, ast.Attribute) and func.attr in {
                "inject_into_headers",
                "extract_from_headers",
            }:
                # ``mq_trace_propagator.inject_into_headers(...)``
                return True
    return False


def _resolve_relative(rel: str) -> Path:
    """Резолвит ``src/backend/...`` относительно project root."""
    return Path(rel)


# ────────────────────── static-analysis locks ──────────────────────


@pytest.mark.parametrize(
    ("file_path", "description"),
    [
        (
            "src/backend/infrastructure/messaging/dlq/kafka_writer.py",
            "KafkaDLQWriter: write → producer.send_and_wait",
        ),
        (
            "src/backend/infrastructure/messaging/dlq/rabbit_writer.py",
            "RabbitDLQWriter: write → exchange.publish(Message(...))",
        ),
        (
            "src/backend/infrastructure/messaging/dlq/nats_writer.py",
            "NATSDLQWriter: write → js.publish(subject, ..., headers=...)",
        ),
        (
            "src/backend/infrastructure/clients/messaging/stream.py",
            "StreamClient: publish_to_{kafka,rabbit} → FastStream router",
        ),
        (
            "src/backend/infrastructure/sources/mq.py",
            "MQSource: _on_message — consumer side extract_from_headers",
        ),
        (
            "src/backend/infrastructure/messaging/outbox/repository.py",
            "OutboxRepository: enqueue — outbox-table headers",
        ),
    ],
)
def test_mq_writer_does_not_inject_w3c_tracecontext(
    file_path: str, description: str,
) -> None:
    """S-L7-5 regression lock: файл НЕ вызывает ``inject_into_headers``.

    Когда wiring состоится (next sprint) — этот тест УДАЛЯЕТСЯ вместе
    с правкой файла. Сейчас — locking current state, документирующий
    carryover S19+ (см. ADR-NEW-FUTURE).
    """
    full_path = _resolve_relative(file_path)
    assert full_path.exists(), f"Файл не найден: {file_path}"
    source = _read(full_path)
    assert not _has_inject_import_or_call(source), (
        f"S-L7-5 REGRESSION: {description} — файл {file_path} "
        f"вызывает inject_into_headers/extract_from_headers. "
        f"Это значит wiring состоялся — ОБНОВИТЕ тест: добавьте "
        f"positive round-trip test + удалите этот lock (см. ADR)."
    )


# ────────────────────── runtime locks (KafkaDLQWriter) ───────────────


@pytest.fixture(autouse=True)
def _reset_otel_tracer_provider() -> Iterator[None]:
    """Сбрасывает global TracerProvider (нужно для чистоты runtime-лока).

    ``KafkaDLQWriter.write`` сейчас НЕ inject'ит traceparent, даже если
    есть active span. Если бы был wiring — мы бы хотели убедиться, что
    active span НЕ «протекает» в headers. Сейчас — гарантируем
    отсутствие любого traceparent.
    """
    import opentelemetry.trace as _trace
    from opentelemetry.util._once import Once

    _trace._TRACER_PROVIDER = None
    _trace._TRACER_PROVIDER_SET_ONCE = Once()
    yield
    _trace._TRACER_PROVIDER = None
    _trace._TRACER_PROVIDER_SET_ONCE = Once()


@pytest.fixture
def _dlq_write_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass ``@require_capability("dlq.write")`` для unit-тестов.

    Auth-фасад в Sprint 4 dev_light не имеет зарегистрированных
    capability — decorator fail-closed. Mock'аем ``check_principal`` →
    ``allowed=True`` чтобы дойти до runtime-блока.
    """
    fake_decision = MagicMock()
    fake_decision.allowed = True
    fake_decision.reason = None
    monkeypatch.setattr(
        "src.backend.services.authorization.facade"
        ".AuthorizationFacade.check_principal",
        AsyncMock(return_value=fake_decision),
    )


def _make_envelope() -> Any:
    """Минимальный DLQEnvelope для runtime-тестов."""
    from src.backend.infrastructure.messaging.dlq import DLQEnvelope, DLQReason

    return DLQEnvelope(
        transport="http",
        error_class="httpx.ConnectTimeout",
        error_message="timeout",
        reason=DLQReason.TIMEOUT,
    )


@pytest.mark.asyncio
async def test_kafka_dlq_writer_does_not_pass_headers_kwarg(
    _dlq_write_allowed: None,
) -> None:
    """S-L7-5 regression: KafkaDLQWriter НЕ передаёт ``headers=`` в producer.

    Текущее поведение (kafka_writer.py:76-80): ``send_and_wait`` вызывается
    БЕЗ kwarg ``headers``. W3C TraceContext propagation невозможен на этом
    слое (S-L7-5 gap).
    """
    from src.backend.infrastructure.messaging.dlq import KafkaDLQWriter

    captured: dict[str, Any] = {}

    async def fake_send_and_wait(topic: str, **kwargs: Any) -> None:
        captured["topic"] = topic
        captured.update(kwargs)

    producer = MagicMock()
    producer.send_and_wait = fake_send_and_wait  # type: ignore[method-assign]

    writer = KafkaDLQWriter(producer=producer)
    await writer.write(_make_envelope())

    # Current state: никаких headers kwarg.
    assert "headers" not in captured, (
        "S-L7-5 REGRESSION: KafkaDLQWriter.write стал передавать headers=... "
        f"в producer.send_and_wait. Captured: {captured!r}. Если это "
        f"запланированный wiring — обновите test и добавьте positive test."
    )
    # Sanity: value/key всё ещё передаются.
    assert "value" in captured
    assert "key" in captured


@pytest.mark.asyncio
async def test_rabbit_dlq_writer_message_lacks_traceparent(
    _dlq_write_allowed: None,
) -> None:
    """S-L7-5 regression: RabbitDLQWriter Message.headers НЕ содержит ``traceparent``.

    Текущее поведение (rabbit_writer.py:61-72): headers содержит только
    ``transport`` / ``reason`` / ``tenant_id`` / ``trace_id`` (envelope-level,
    НЕ W3C TraceContext). W3C ``traceparent`` отсутствует.
    """
    from aio_pika import DeliveryMode, Message

    from src.backend.infrastructure.messaging.dlq import RabbitDLQWriter

    captured: dict[str, Any] = {}

    class FakeExchange:
        async def publish(self, message: Any, **kwargs: Any) -> None:
            captured["message"] = message
            captured["publish_kwargs"] = kwargs

    class FakeChannel:
        default_exchange = FakeExchange()

    writer = RabbitDLQWriter(channel=FakeChannel())
    await writer.write(_make_envelope())

    message: Message = captured["message"]
    # Current state: W3C ``traceparent`` НЕ присутствует.
    assert "traceparent" not in message.headers, (
        "S-L7-5 REGRESSION: RabbitDLQWriter теперь inject'ит W3C "
        f"traceparent. headers={message.headers!r}. Если это запланированный "
        f"wiring — обновите test и добавьте positive test."
    )
    # Sanity: базовые headers всё ещё на месте.
    assert "transport" in message.headers
    assert "tenant_id" in message.headers
    # delivery_mode — persistent (PERSISTENT == 2).
    assert message.delivery_mode == DeliveryMode.PERSISTENT


@pytest.mark.asyncio
async def test_nats_dlq_writer_message_lacks_traceparent(
    _dlq_write_allowed: None,
) -> None:
    """S-L7-5 regression: NATSDLQWriter headers НЕ содержат ``traceparent``.

    Текущее поведение (nats_writer.py:54-59): передаёт
    ``Nats-Msg-Id`` / ``X-Transport`` / ``X-Tenant`` / ``X-Trace``
    (envelope-level). W3C ``traceparent`` отсутствует.
    """
    from src.backend.infrastructure.messaging.dlq import NATSDLQWriter

    captured: dict[str, Any] = {}

    class FakeJetStream:
        async def publish(self, subject: str, payload: Any, **kwargs: Any) -> None:
            captured["subject"] = subject
            captured["payload"] = payload
            captured.update(kwargs)

    writer = NATSDLQWriter(jetstream=FakeJetStream())
    await writer.write(_make_envelope())

    headers = captured.get("headers", {})
    assert "traceparent" not in headers, (
        "S-L7-5 REGRESSION: NATSDLQWriter теперь inject'ит W3C traceparent. "
        f"headers={headers!r}."
    )
    # Sanity: текущий contract headers — сохранён.
    assert "Nats-Msg-Id" in headers
    assert "X-Transport" in headers
