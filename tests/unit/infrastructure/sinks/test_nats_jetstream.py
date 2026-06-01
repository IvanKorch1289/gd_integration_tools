"""K3 W2 — unit-тесты NATSJetStreamSink.

Покрывают:

* публикацию payload в JetStream subject;
* передачу headers в publish();
* graceful ImportError при отсутствии nats-py;
* контракт SinkKind.NATS_JS.

Импорт NATSJetStreamSink выполняется напрямую (минуя sinks/__init__.py),
чтобы не тянуть всю цепочку settings (codec → converters → logging_service).
"""

# ruff: noqa: S101, I001

from __future__ import annotations

import importlib.util as _ilu
import pathlib as _pl
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# Прямой импорт без triggering sinks/__init__.py
from src.backend.core.interfaces.sink import SinkKind  # noqa: E402

_sink_path = (
    _pl.Path(__file__).parent.parent.parent.parent.parent
    / "src/backend/infrastructure/sinks/nats_jetstream.py"
)
_spec = _ilu.spec_from_file_location("src.backend.infrastructure.sinks.nats_jetstream", _sink_path)
_mod = _ilu.module_from_spec(_spec)
sys.modules.setdefault("src.backend.infrastructure.sinks.nats_jetstream", _mod)
_spec.loader.exec_module(_mod)
NATSJetStreamSink = _mod.NATSJetStreamSink


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики


def _make_fake_ack(stream: str = "ORDERS", seq: int = 1) -> MagicMock:
    """Создаёт mock PublishAck."""
    ack = MagicMock()
    ack.stream = stream
    ack.seq = seq
    return ack


def _install_fake_nats(
    monkeypatch: pytest.MonkeyPatch,
    ack: MagicMock | None = None,
    raise_on_publish: Exception | None = None,
) -> MagicMock:
    """Устанавливает fake nats в sys.modules.

    Returns:
        Fake nc (connection) mock для дополнительных assertions.
    """
    js = MagicMock()
    if raise_on_publish is not None:
        js.publish = AsyncMock(side_effect=raise_on_publish)
    else:
        js.publish = AsyncMock(return_value=ack or _make_fake_ack())

    nc = MagicMock()
    nc.is_closed = False
    nc.jetstream = MagicMock(return_value=js)
    nc.drain = AsyncMock()
    nc.close = AsyncMock()

    fake_nats = types.ModuleType("nats")
    fake_nats.connect = AsyncMock(return_value=nc)  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "nats", fake_nats)
    return nc


# ──────────────────────────────────────────────────────────────────────────────
# Тесты


@pytest.mark.asyncio
async def test_sink_publishes_to_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """NATSJetStreamSink.publish() успешно публикует данные в subject."""
    nc = _install_fake_nats(monkeypatch, ack=_make_fake_ack(stream="ORDERS", seq=42))

    sink = NATSJetStreamSink(
        sink_id="orders.nats_js",
        nats_url="nats://localhost:4222",
        default_subject="orders.created",
    )

    result = await sink.publish("orders.created", b'{"order_id": 99}')

    assert result.ok is True
    assert result.external_id == "42"
    assert result.details["subject"] == "orders.created"
    assert result.details["stream"] == "ORDERS"
    assert result.details["seq"] == 42

    # Проверяем что nc.drain() и nc.close() вызваны (cleanup)
    nc.drain.assert_awaited_once()
    nc.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_sink_passes_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """NATSJetStreamSink.publish() передаёт headers в js.publish()."""
    nc = _install_fake_nats(monkeypatch)
    js = nc.jetstream()

    sink = NATSJetStreamSink(
        sink_id="payments.nats_js",
        nats_url="nats://nats.internal:4222",
        default_subject="payments.processed",
    )
    headers = {"X-Tenant": "bank1", "X-Source": "payment-api"}

    result = await sink.publish("payments.processed", b'{"amount": 500}', headers=headers)

    assert result.ok is True
    # Проверяем что headers были переданы в js.publish()
    js.publish.assert_awaited_once()
    call_kwargs = js.publish.call_args
    assert call_kwargs is not None
    published_headers = call_kwargs.kwargs.get("headers")
    assert published_headers == headers


@pytest.mark.asyncio
async def test_sink_returns_error_when_nats_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При отсутствии nats-py publish() возвращает SinkResult(ok=False)."""
    monkeypatch.setitem(sys.modules, "nats", None)  # type: ignore[arg-type]

    sink = NATSJetStreamSink(sink_id="test.nats_js")
    result = await sink.publish("test.subject", b"data")

    assert result.ok is False
    assert "nats-py" in result.details["error"]


@pytest.mark.asyncio
async def test_sink_send_serializes_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """NATSJetStreamSink.send() сериализует dict через orjson и публикует."""
    _install_fake_nats(monkeypatch)

    sink = NATSJetStreamSink(
        sink_id="events.nats_js",
        default_subject="events.dispatched",
    )

    result = await sink.send({"event": "order_created", "id": 7})

    assert result.ok is True


def test_sink_kind_is_nats_js() -> None:
    """NATSJetStreamSink.kind равен SinkKind.NATS_JS."""
    sink = NATSJetStreamSink(sink_id="s1")
    assert sink.kind == SinkKind.NATS_JS
