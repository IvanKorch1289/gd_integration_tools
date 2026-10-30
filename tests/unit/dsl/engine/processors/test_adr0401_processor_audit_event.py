"""ADR-0401 — ``audit_event`` процессоров эмитится базовым классом.

ADR-0370: ``audit_event`` был объявлен более чем 40 классами процессоров, но
**ни один потребитель его не читал** — событие не создавалось. Единственный
потребитель был в ``agent_dsl/_base.py`` (AI-процессоры), остальные шаги
молча оставались без audit-записи.

ADR-0401: эмиссия перенесена в базовый класс
(:class:`BaseProcessor`), чтобы не править 40+ классов:

* шаг с ``audit_event`` → событие создаётся после выполнения;
* шаг без ``audit_event`` → события нет;
* AI-процессоры (``BaseAIProcessor``) эмитят событие сами — дубликата нет;
* в payload события — только метаданные (capability/маршрут/tenant),
  **никаких значений данных**.
"""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.base import BaseProcessor

pytestmark = pytest.mark.unit


class _AuditedProcessor(BaseProcessor):
    """Тестовый процессор с объявленным ``audit_event``."""

    required_capability: ClassVar[str | None] = "test.capability"
    audit_event: ClassVar[str | None] = "test.audit.event"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Ничего не делает — проверяется только audit-обвязка."""
        del context
        exchange.set_property("done", True)


class _PlainProcessor(BaseProcessor):
    """Тестовый процессор БЕЗ ``audit_event``."""

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Ничего не делает."""
        del context
        exchange.set_property("done", True)


class _FailingProcessor(BaseProcessor):
    """Тестовый процессор, падающий с исключением."""

    audit_event: ClassVar[str | None] = "test.audit.failure"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Кидает исключение."""
        del exchange, context
        raise RuntimeError("boom")


def _exchange() -> Exchange[Any]:
    """Пустой exchange."""
    return Exchange(in_message=Message(body={}, headers={}))


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Перехватывает вызовы ``emit_audit`` (canonical audit-facade)."""
    calls: list[dict[str, Any]] = []

    def _fake_emit_audit(event: str, **kwargs: Any) -> None:
        calls.append({"event": event, **kwargs})

    monkeypatch.setattr(
        "src.backend.core.audit.facade.emit_audit", _fake_emit_audit, raising=True
    )
    return calls


# ── эмиссия ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_processor_with_audit_event_emits(emitted: list[dict[str, Any]]) -> None:
    """Шаг с ``audit_event`` создаёт событие."""
    await _AuditedProcessor().process(_exchange(), MagicMock())

    assert len(emitted) == 1
    assert emitted[0]["event"] == "test.audit.event"
    assert emitted[0]["outcome"] == "success"
    assert emitted[0]["action"] == "process"


@pytest.mark.asyncio
async def test_processor_without_audit_event_is_silent(
    emitted: list[dict[str, Any]],
) -> None:
    """Шаг без ``audit_event`` не создаёт событие."""
    await _PlainProcessor().process(_exchange(), MagicMock())

    assert emitted == []


@pytest.mark.asyncio
async def test_audit_details_have_capability_but_no_data(
    emitted: list[dict[str, Any]],
) -> None:
    """В событие попадает capability и НЕ попадают значения данных."""
    exchange = _exchange()
    exchange.in_message.body = {"secret": "super-secret-value"}

    await _AuditedProcessor().process(exchange, MagicMock())

    details = emitted[0]["details"]
    assert details["capability"] == "test.capability"
    assert details["processor_class"] == "_AuditedProcessor"
    assert "super-secret-value" not in str(details)


@pytest.mark.asyncio
async def test_failed_step_emits_failure_outcome(
    emitted: list[dict[str, Any]],
) -> None:
    """Упавший шаг эмитит событие с outcome=failure."""
    with pytest.raises(RuntimeError):
        await _FailingProcessor().process(_exchange(), MagicMock())

    assert len(emitted) == 1
    assert emitted[0]["outcome"] == "failure"


@pytest.mark.asyncio
async def test_failed_exchange_emits_failure_outcome(
    emitted: list[dict[str, Any]],
) -> None:
    """Шаг, пометивший exchange как failed, эмитит outcome=failure."""

    class _FailingExchangeProcessor(BaseProcessor):
        audit_event: ClassVar[str | None] = "test.audit.failed"

        async def process(self, exchange: Exchange[Any], context: Any) -> None:
            """Помечает exchange как failed."""
            del context
            exchange.fail("boom")

    await _FailingExchangeProcessor().process(_exchange(), MagicMock())

    assert len(emitted) == 1
    assert emitted[0]["outcome"] == "failure"


# ── AI-процессоры не дублируют событие ────────────────────────────────────


def test_ai_processors_are_not_double_wrapped() -> None:
    """AI-процессоры эмитят audit сами — базовая обвязка их не трогает."""
    from src.backend.dsl.engine.processors.agent_dsl.agent_run import AgentRunProcessor
    from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
        LangGraphAgentProcessor,
    )

    assert not getattr(AgentRunProcessor.process, "__audit_wrapped__", False)
    assert getattr(LangGraphAgentProcessor.process, "__audit_wrapped__", False)


@pytest.mark.asyncio
async def test_real_rpa_processor_emits_audit_event(
    emitted: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Реальный RPA-процессор создаёт объявленное событие."""
    from src.backend.dsl.engine.processors.rpa.operations.hashprocessor import (
        HashProcessor,
    )

    monkeypatch.setattr(
        HashProcessor, "auth_check", AsyncMock(return_value=True)
    )
    exchange = _exchange()
    exchange.in_message.body = {"a": 1}

    await HashProcessor(algorithm="sha256").process(exchange, MagicMock())

    assert len(emitted) == 1
    assert emitted[0]["event"] == "rpa.hash.compute"
    assert emitted[0]["details"]["capability"] == "rpa.hash.compute"
