"""TransactionalClient + ProcessManager EIP-процессоры (S63 W3).

Apache Camel EIP patterns, отсутствовавшие в V22:
* :class:`TransactionalClientProcessor` — Transactional Client (exactly-once
  через outbox pattern). Сначала выполняет user-action, потом enqueue outbox
  event. Если action fails → НЕ enqueue. Если enqueue fails → exchange.fail.
  Для full exactly-once semantics оберните в DB transaction (на стороне
  пользователя); этот processor гарантирует только ordering.
* :class:`ProcessManagerProcessor` — Process Manager (long-running
  orchestration с state-persist). Реализован как thin facade над
  :class:`src.backend.dsl.engine.processors.control_flow.SagaProcessor`
  с включённой опцией ``persist_state=True`` (через WorkflowState SQLAlchemy
  repo из S21 K3 W3).

S63 W3.0 — facade-only: 0 production-логики дублируется, только DSL-фасад
поверх уже существующих Saga + Outbox.

Usage::

    # Transactional Client
    .transactional_client(
        action=lambda ex: ex.set_out(body={"order_id": 123}),
        outbox_backend=lambda: outbox,    # OutboxBackend instance
        event_factory=lambda ex, res: OutboxEvent(
            topic="orders", payload=res.body, status=OutboxEventStatus.PENDING,
        ),
    )

    # Process Manager (alias SagaProcessor + persist_state)
    .process_manager(
        steps=[step_a, step_b, step_c],
        persist_state=True,        # опционально: через WorkflowState repo
    )
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.engine.processors.control_flow import SagaProcessor, SagaStep

if TYPE_CHECKING:
    from src.backend.core.messaging.outbox import OutboxBackend, OutboxEvent
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("ProcessManagerProcessor", "TransactionalClientProcessor")


#: Сигнатура user-action для TransactionalClient.
ActionCallable = Callable[["Exchange[Any]"], Awaitable[Any]]

#: Сигнатура event-factory для TransactionalClient.
EventFactoryCallable = Callable[["Exchange[Any]", Any], "OutboxEvent"]

#: Сигнатура outbox-factory для TransactionalClient.
OutboxFactoryCallable = Callable[[], "OutboxBackend"]


class TransactionalClientProcessor(BaseProcessor):
    """Camel Transactional Client EIP — at-least-once via outbox pattern.

    Семантика:
        1. ``await action(exchange)`` — user action (side-effect).
        2. ``event = event_factory(exchange, action_result)`` — построить event.
        3. ``await outbox_backend.enqueue(event)`` — durable queue.

    Failure modes:
        * ``action`` raises или ``exchange.status == failed`` →
          ``exchange.fail("action failed")``, НЕ enqueue.
        * ``enqueue`` raises → ``exchange.fail("outbox enqueue failed")``;
          recovery needed (event lost, manual replay).
        * User-action side-effects УЖЕ произошли (DB write, etc.) — откат
          на стороне пользователя через компенсацию.

    Exactly-once: для full EoS оберните ``action + enqueue`` в DB transaction
    (одна ``session.begin()`` + ``action`` + ``enqueue`` + ``session.commit()``).
    Этот processor гарантирует только ordering, не atomicity.

    Note:
        Альтернатива для batch-import: используйте
        :class:`src.backend.infrastructure.messaging.outbox.dispatcher.OutboxDispatcher`
        для background polling/delivery. TransactionalClient — для
        synchronous в-execution-flow enqueue.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        action: ActionCallable,
        outbox_backend: OutboxFactoryCallable,
        event_factory: EventFactoryCallable,
        name: str | None = None,
    ) -> None:
        if not callable(action):
            raise ValueError(f"action must be callable, got {type(action).__name__}")
        if not callable(outbox_backend):
            raise ValueError(
                f"outbox_backend must be callable, got {type(outbox_backend).__name__}"
            )
        if not callable(event_factory):
            raise ValueError(
                f"event_factory must be callable, got {type(event_factory).__name__}"
            )
        super().__init__(name=name or "transactional_client")
        self._action = action
        self._outbox_backend_factory = outbox_backend
        self._event_factory = event_factory

    @handle_processor_error
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        # 1. Run user action. Если падает — НЕ enqueue.
        try:
            action_result = await self._action(exchange)
        except Exception as exc:
            exchange.fail(f"transactional_client action failed: {exc}")
            return

        if exchange.status.name == "failed":
            # Action сам пометил exchange как failed
            return

        # 2. Build event
        try:
            event = self._event_factory(exchange, action_result)
        except Exception as exc:
            exchange.fail(f"transactional_client event_factory failed: {exc}")
            return

        # 3. Enqueue to outbox. Если падает — manual recovery needed.
        try:
            backend = self._outbox_backend_factory()
            await backend.enqueue(event)
        except Exception as exc:
            exchange.fail(f"transactional_client enqueue failed: {exc}")
            return

        exchange.set_property("transactional_client_enqueued", True)


class ProcessManagerProcessor(SagaProcessor):
    """Camel Process Manager EIP — long-running orchestration с state persist.

    Это thin-facade над :class:`SagaProcessor` с добавлением опции
    ``persist_state`` (через WorkflowState SQLAlchemy repo из S21 K3 W3).

    Семантика:
        * Если ``persist_state=False`` — поведение идентично SagaProcessor.
        * Если ``persist_state=True`` — после каждого completed step
          saga-состояние сериализуется в ``workflow_state`` таблицу
          (через :class:`src.backend.core.orchestration.saga_state.SagaStateStore`).
          При restart процесс может восстановить progress.

    Note:
        Это не полноценный Process Manager из EIP-канона (который требует
        external message correlation + state-machine). Для full PM см.
        :class:`src.backend.dsl.workflow.builder.WorkflowBuilder` + Temporal
        backend (``LiteTemporalBackend``). Этот processor — DSL-фасад для
        inline orchestration в route, без external state-machine.
    """

    def __init__(
        self,
        steps: list[SagaStep],
        *,
        persist_state: bool = False,
        saga_state_store: Callable[[], Any] | None = None,
        name: str | None = None,
    ) -> None:
        if persist_state and saga_state_store is None:
            raise ValueError(
                "saga_state_store обязателен при persist_state=True "
                "(фабрика, возвращающая SagaStateStore-compatible instance)"
            )
        super().__init__(steps, name=name or f"process_manager({len(steps)} steps)")
        self._persist_state = persist_state
        self._saga_state_store_factory = saga_state_store
