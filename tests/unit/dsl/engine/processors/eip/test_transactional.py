"""Unit-тесты eip/transactional.py: TransactionalClient + ProcessManager (S63 W3).

S63 W3.0 — facade-only EIP-patterns. TransactionalClient — outbox via
OutboxBackend.enqueue. ProcessManager — facade над SagaProcessor с
опциональной persist_state.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.messaging.outbox import OutboxEvent, OutboxEventStatus
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.transactional import (
    ProcessManagerProcessor,
    TransactionalClientProcessor,
)


def _make_exchange(body: Any = None) -> Exchange:
    msg = Message(body=body, headers={})
    return Exchange(in_message=msg, out_message=msg)


def _make_outbox_backend() -> Any:
    """Mocked OutboxBackend с enqueue."""
    backend = MagicMock()
    backend.enqueue = AsyncMock()
    return backend


def _make_event() -> OutboxEvent:
    return OutboxEvent(transport="http", action="test.api", payload={"id": 1})


# ─── TransactionalClient ────────────────────────────────────────────


class TestTransactionalClientInit:
    def test_init_minimal(self) -> None:
        async def action(ex: Exchange) -> dict:
            return {}

        p = TransactionalClientProcessor(
            action=action,
            outbox_backend=lambda: _make_outbox_backend(),
            event_factory=lambda ex, res: _make_event(),
        )
        assert p.name == "transactional_client"

    def test_init_custom_name(self) -> None:
        async def action(ex: Exchange) -> dict:
            return {}

        p = TransactionalClientProcessor(
            action=action,
            outbox_backend=lambda: _make_outbox_backend(),
            event_factory=lambda ex, res: _make_event(),
            name="order_outbox",
        )
        assert p.name == "order_outbox"

    def test_init_action_not_callable_raises(self) -> None:
        with pytest.raises(ValueError, match="action must be callable"):
            TransactionalClientProcessor(
                action="not-callable",  # type: ignore[arg-type]
                outbox_backend=lambda: _make_outbox_backend(),
                event_factory=lambda ex, res: _make_event(),
            )

    def test_init_backend_not_callable_raises(self) -> None:
        async def action(ex: Exchange) -> dict:
            return {}

        with pytest.raises(ValueError, match="outbox_backend must be callable"):
            TransactionalClientProcessor(
                action=action,
                outbox_backend=42,  # type: ignore[arg-type]
                event_factory=lambda ex, res: _make_event(),
            )

    def test_init_event_factory_not_callable_raises(self) -> None:
        async def action(ex: Exchange) -> dict:
            return {}

        with pytest.raises(ValueError, match="event_factory must be callable"):
            TransactionalClientProcessor(
                action=action,
                outbox_backend=lambda: _make_outbox_backend(),
                event_factory=None,  # type: ignore[arg-type]
            )


class TestTransactionalClientHappyPath:
    async def test_action_runs_then_enqueue(self) -> None:
        backend = _make_outbox_backend()
        called: list[str] = []

        async def action(ex: Exchange) -> dict:
            called.append("action")
            return {"order_id": 42}

        def event_factory(ex: Exchange, result: Any) -> OutboxEvent:
            called.append("event_factory")
            return OutboxEvent(
                transport="kafka",
                action="orders.create",
                payload=result,
                status=OutboxEventStatus.PENDING,
            )

        p = TransactionalClientProcessor(
            action=action, outbox_backend=lambda: backend, event_factory=event_factory
        )
        ex = _make_exchange({"input": 1})
        await p.process(ex, context=MagicMock())

        # Action запустился ДО enqueue
        assert called == ["action", "event_factory"]
        backend.enqueue.assert_awaited_once()
        # Success: status НЕ failed, enqueued=True
        assert ex.status != ExchangeStatus.failed
        assert ex.get_property("transactional_client_enqueued") is True

    async def test_event_factory_receives_action_result(self) -> None:
        backend = _make_outbox_backend()
        captured: dict[str, Any] = {}

        async def action(ex: Exchange) -> dict:
            return {"id": 99}

        def event_factory(ex: Exchange, result: Any) -> OutboxEvent:
            captured["result"] = result
            captured["body"] = ex.in_message.body
            return _make_event()

        p = TransactionalClientProcessor(
            action=action, outbox_backend=lambda: backend, event_factory=event_factory
        )
        await p.process(_make_exchange({"input": "x"}), context=MagicMock())

        assert captured["result"] == {"id": 99}
        assert captured["body"] == {"input": "x"}


class TestTransactionalClientFailureModes:
    async def test_action_exception_does_not_enqueue(self) -> None:
        backend = _make_outbox_backend()

        async def failing_action(ex: Exchange) -> dict:
            raise ValueError("action boom")

        p = TransactionalClientProcessor(
            action=failing_action,
            outbox_backend=lambda: backend,
            event_factory=lambda ex, res: _make_event(),
        )
        ex = _make_exchange()
        await p.process(ex, context=MagicMock())

        backend.enqueue.assert_not_called()
        assert ex.status == ExchangeStatus.failed
        assert "action boom" in (ex.error or "")

    async def test_action_marks_exchange_failed_no_enqueue(self) -> None:
        """Action сам помечает exchange.failed → не enqueue."""
        backend = _make_outbox_backend()

        async def failing_action(ex: Exchange) -> dict:
            ex.fail("custom failure")
            return {}

        p = TransactionalClientProcessor(
            action=failing_action,
            outbox_backend=lambda: backend,
            event_factory=lambda ex, res: _make_event(),
        )
        ex = _make_exchange()
        await p.process(ex, context=MagicMock())

        backend.enqueue.assert_not_called()
        assert ex.status == ExchangeStatus.failed

    async def test_event_factory_exception_marks_failed(self) -> None:
        backend = _make_outbox_backend()

        async def action(ex: Exchange) -> dict:
            return {}

        def bad_event_factory(ex: Exchange, res: Any) -> OutboxEvent:
            raise TypeError("event factory boom")

        p = TransactionalClientProcessor(
            action=action,
            outbox_backend=lambda: backend,
            event_factory=bad_event_factory,
        )
        ex = _make_exchange()
        await p.process(ex, context=MagicMock())

        backend.enqueue.assert_not_called()
        assert ex.status == ExchangeStatus.failed
        assert "event factory boom" in (ex.error or "")

    async def test_enqueue_exception_marks_failed(self) -> None:
        backend = _make_outbox_backend()
        backend.enqueue.side_effect = RuntimeError("kafka down")

        async def action(ex: Exchange) -> dict:
            return {"id": 1}

        p = TransactionalClientProcessor(
            action=action,
            outbox_backend=lambda: backend,
            event_factory=lambda ex, res: _make_event(),
        )
        ex = _make_exchange()
        await p.process(ex, context=MagicMock())

        backend.enqueue.assert_awaited_once()
        assert ex.status == ExchangeStatus.failed
        assert "kafka down" in (ex.error or "")
        # Свойство НЕ выставлено (т.к. enqueue упал)
        assert ex.get_property("transactional_client_enqueued") is None


# ─── ProcessManager ──────────────────────────────────────────────────


def _make_failing_step() -> Any:
    """Шаг, который всегда fails при process()."""
    step = MagicMock(spec=BaseProcessor)
    step.process = AsyncMock(side_effect=RuntimeError("step failed"))
    return step


def _make_succeeding_step() -> Any:
    step = MagicMock(spec=BaseProcessor)
    step.process = AsyncMock()
    return step


class TestProcessManagerInit:
    def test_init_no_persist(self) -> None:
        pm = ProcessManagerProcessor(steps=[])
        assert pm._persist_state is False

    def test_init_persist_state_without_store_raises(self) -> None:
        with pytest.raises(ValueError, match="saga_state_store обязателен"):
            ProcessManagerProcessor(steps=[], persist_state=True)

    def test_init_persist_state_with_store_ok(self) -> None:
        pm = ProcessManagerProcessor(
            steps=[], persist_state=True, saga_state_store=lambda: MagicMock()
        )
        assert pm._persist_state is True


class TestProcessManagerAliasing:
    """ProcessManager = SagaProcessor + persist_state. Базовое поведение
    идентично SagaProcessor при persist_state=False."""

    async def test_succeeds_without_persist(self) -> None:
        pm = ProcessManagerProcessor(steps=[])  # пустой — no-op saga
        ex = _make_exchange()
        await pm.process(ex, context=MagicMock())
        # Saga с 0 шагов = success (saga_completed=True), status не failed
        assert ex.get_property("saga_completed") is True
        assert ex.status != ExchangeStatus.failed

    async def test_saga_failure_triggers_compensation(self) -> None:
        step1 = _make_succeeding_step()
        step2 = _make_succeeding_step()
        step2.compensate = _make_succeeding_step()
        step3 = _make_failing_step()
        from src.backend.dsl.engine.processors.control_flow import SagaStep

        pm = ProcessManagerProcessor(
            steps=[
                SagaStep(forward=step1, compensate=None),
                SagaStep(forward=step2, compensate=step2.compensate),
                SagaStep(forward=step3, compensate=None),
            ]
        )
        ex = _make_exchange()
        await pm.process(ex, context=MagicMock())

        # step3 failed → compensations for step2 and step1
        step2.compensate.process.assert_awaited_once()
        assert ex.status == ExchangeStatus.failed


# ─── Side-effect class vars ─────────────────────────────────────────


class TestClassVars:
    def test_transactional_client_side_effect(self) -> None:
        async def action(ex: Exchange) -> dict:
            return {}

        p = TransactionalClientProcessor(
            action=action,
            outbox_backend=lambda: _make_outbox_backend(),
            event_factory=lambda ex, res: _make_event(),
        )
        # SIDE_EFFECTING (записывает в outbox) + compensatable
        from src.backend.core.types.side_effect import SideEffectKind

        assert p.side_effect == SideEffectKind.SIDE_EFFECTING
        assert p.compensatable is True
