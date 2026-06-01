"""Sprint 3 — unit-тесты EmailSource (V16.1 P1).

Покрывают:

* фильтрацию по теме/отправителю (substring + regex);
* контракт ``EmailSource.matches()`` для произвольного payload;
* совместимость EmailTriggerProcessor с парсенным IMAP-payload.

Сетевая часть (IDLE/polling-loop) НЕ тестируется здесь — для неё нужен
интеграционный тест с фейковым IMAP-сервером (отдельно, Wave R3).
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.interfaces.source import SourceKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.email_trigger import EmailTriggerProcessor
from src.backend.infrastructure.sources.email import EmailSource


def _src(**overrides: object) -> EmailSource:
    """Фабрика EmailSource с дефолтами под тесты."""
    cfg: dict[str, object] = {
        "host": "imap.example.com",
        "username": "user",
        "password": "pwd",
        "idle_mode": False,
    }
    cfg.update(overrides)
    return EmailSource(source_id="es-test", **cfg)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("subject_pattern", "subject", "expected"),
    [
        (None, "Anything", True),
        ("INVOICE", "Re: INVOICE-42", True),
        ("invoice", "Invoice from Acme", True),
        ("INVOICE", "Hello world", False),
        ("re:^URGENT", "URGENT: take action", True),
        ("re:^URGENT", "Re: urgent ticket", False),
    ],
)
def test_subject_filter(
    subject_pattern: str | None, subject: str, expected: bool
) -> None:
    src = _src(subject_pattern=subject_pattern)
    assert src.matches({"subject": subject, "from": "x@y"}) is expected


@pytest.mark.parametrize(
    ("from_filter", "sender", "expected"),
    [
        (None, "anyone@example.com", True),
        ("acme.com", "billing@ACME.com", True),
        ("acme.com", "noreply@other.io", False),
        ("BILLING", "Billing Dept <billing@example.com>", True),
    ],
)
def test_from_filter(from_filter: str | None, sender: str, expected: bool) -> None:
    src = _src(from_filter=from_filter)
    assert src.matches({"subject": "x", "from": sender}) is expected


def test_kind_is_email() -> None:
    src = _src()
    assert src.kind == SourceKind.EMAIL
    assert src.source_id == "es-test"


def test_combined_filters_both_must_match() -> None:
    src = _src(subject_pattern="INVOICE", from_filter="acme.com")
    assert src.matches({"subject": "INVOICE-42", "from": "billing@acme.com"}) is True
    assert src.matches({"subject": "INVOICE-42", "from": "x@y.com"}) is False
    assert src.matches({"subject": "Hello", "from": "billing@acme.com"}) is False


def test_default_state_no_running_task() -> None:
    src = _src()
    assert src._task is None
    # health() — async, проверим состояние через атрибуты
    assert src._cfg.host == "imap.example.com"
    assert src._cfg.idle_mode is False


# ──────────────── EmailTriggerProcessor ──────────────────────────────────


def _exchange(body: object) -> Exchange:
    return Exchange(in_message=Message(body=body))


@pytest.mark.asyncio
async def test_email_trigger_passes_when_match() -> None:
    proc = EmailTriggerProcessor(subject_pattern="INVOICE")
    exchange = _exchange({"subject": "INVOICE-42", "from": "a@b"})
    context = ExecutionContext(route_id="r")
    await proc.process(exchange, context)
    assert exchange.stopped is False
    assert exchange.in_message.headers.get("x-email-subject") == "INVOICE-42"
    assert exchange.in_message.headers.get("x-email-from") == "a@b"


@pytest.mark.asyncio
async def test_email_trigger_stops_when_no_match() -> None:
    proc = EmailTriggerProcessor(subject_pattern="INVOICE")
    exchange = _exchange({"subject": "Hello", "from": "a@b"})
    context = ExecutionContext(route_id="r")
    await proc.process(exchange, context)
    assert exchange.stopped is True


@pytest.mark.asyncio
async def test_email_trigger_does_not_propagate_when_disabled() -> None:
    proc = EmailTriggerProcessor(
        subject_pattern="INVOICE", propagate_metadata=False
    )
    exchange = _exchange({"subject": "INVOICE-42", "from": "a@b"})
    context = ExecutionContext(route_id="r")
    await proc.process(exchange, context)
    assert exchange.stopped is False
    assert "x-email-subject" not in exchange.in_message.headers


@pytest.mark.asyncio
async def test_email_trigger_stops_when_body_not_dict() -> None:
    proc = EmailTriggerProcessor(subject_pattern="INVOICE")
    exchange = _exchange("not a dict")
    context = ExecutionContext(route_id="r")
    await proc.process(exchange, context)
    assert exchange.stopped is True


def test_email_trigger_to_spec_round_trip() -> None:
    proc = EmailTriggerProcessor(
        subject_pattern="INVOICE", from_filter="acme.com", propagate_metadata=False
    )
    spec = proc.to_spec()
    assert spec == {
        "email_trigger": {
            "subject_pattern": "INVOICE",
            "from_filter": "acme.com",
            "propagate_metadata": False,
        }
    }


def test_email_trigger_does_not_match_non_dict_body() -> None:
    proc = EmailTriggerProcessor(subject_pattern="INVOICE")
    assert proc.matches("not a dict") is False
    assert proc.matches(None) is False
    assert proc.matches(["list"]) is False
