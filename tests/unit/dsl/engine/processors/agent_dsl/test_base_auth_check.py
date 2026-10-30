"""ADR-0400: ``BaseAIProcessor`` обязан вызывать ``auth_check`` (ADR-0366 G12.2).

Дефект: 13 классов ``agent_dsl/*`` объявляют ``required_capability``, но
``BaseAIProcessor.process()`` capability **не проверял** — декларация была
без эффекта (проверка шла в обход канонического ``auth_check``, который
учитывает feature-флаг ``dsl_capability_gate_enabled`` и fail-closed
поведение).

После фикса ``process()``:
* вызывает ``await self.auth_check(...)`` ДО ``_run``;
* при отказе действие НЕ выполняется, exchange переводится в ``failed``
  (fail-closed, ADR-0393).

Модуль отключает autouse-фикстуру ``patched_db_capability_allow``
(см. ``tests/unit/dsl/engine/processors/conftest.py``) — здесь проверяется
настоящий capability-гейт.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

#:Capability-гейт проверяется по-настоящему (без autouse-подмены).
REAL_CAPABILITY_GATE = True


class _StubProcessor(BaseAIProcessor):
    """Минимальный AI-процессор: записывает факт вызова ``_run``."""

    required_capability: str | None = "ai.invoke"

    def __init__(self) -> None:
        super().__init__(name="stub")
        self.run_calls = 0

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Считает вызовы core-логики.

        Args:
            exchange: DSL Exchange (не используется).
            context: Execution context (не используется).

        """
        del exchange, context
        self.run_calls += 1


def _exchange() -> Exchange[Any]:
    """Создать Exchange с tenant-контекстом.

    Returns:
        Exchange с установленным ``tenant_id``.
    """
    exchange: Exchange[Any] = Exchange(in_message=Message(body={}))
    exchange.meta.tenant_id = "acme"
    return exchange


@pytest.mark.asyncio
async def test_process_calls_auth_check_before_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``auth_check`` вызывается до core-логики процессора."""
    processor = _StubProcessor()
    order: list[str] = []

    async def _allow(
        self: Any,
        exchange: Any,
        *,
        action: str = "execute",
        principal: str | None = None,
    ) -> bool:
        del self, exchange, action, principal
        order.append("auth_check")
        return True

    monkeypatch.setattr(BaseAIProcessor, "auth_check", _allow)

    await processor.process(_exchange(), ExecutionContext())

    assert order == ["auth_check"]
    assert processor.run_calls == 1


@pytest.mark.asyncio
async def test_denied_capability_does_not_run_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ capability-гейта → core-логика НЕ выполняется (fail-closed)."""
    processor = _StubProcessor()
    exchange = _exchange()

    async def _deny(
        self: Any,
        exchange: Any,
        *,
        action: str = "execute",
        principal: str | None = None,
    ) -> bool:
        del self, action, principal
        exchange.fail("capability 'ai.invoke' denied")
        exchange.stop()
        return False

    monkeypatch.setattr(BaseAIProcessor, "auth_check", _deny)

    await processor.process(exchange, ExecutionContext())

    assert processor.run_calls == 0
    assert exchange.status is ExchangeStatus.failed
    assert exchange.error is not None


@pytest.mark.asyncio
async def test_unknown_capability_is_denied_by_runtime_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Незаявленная capability → fail-closed DENY, действие не выполняется."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "dsl_capability_gate_enabled", True)

    class _UnknownCapabilityProcessor(_StubProcessor):
        """Процессор с capability, которой нет ни в одном namespace."""

        required_capability: str | None = "ai.unknown.capability"

    processor = _UnknownCapabilityProcessor()
    exchange = _exchange()

    await processor.process(exchange, ExecutionContext())

    assert processor.run_calls == 0
    assert exchange.status is ExchangeStatus.failed
    assert "denied" in (exchange.error or "")
