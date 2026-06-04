"""Lifecycle hooks для :class:`OutboxDispatcher` (S8A K2 W2).

Hooks предназначены к подключению координатором в
``plugins/composition/lifecycle.py`` через named-block. В рамках текущей
wave файл создаётся, но **не** trigger'ится — этим займётся координатор.

Контракт hooks:

* :func:`start_outbox_dispatcher` — создаёт и стартует диспетчер,
  кладёт ссылку в ``app.state.outbox_dispatcher``. При ``enabled=False``
  — no-op.
* :func:`stop_outbox_dispatcher` — graceful shutdown с timeout из
  настроек. Очищает ``app.state.outbox_dispatcher``.

Обе функции идемпотентны: повторный вызов без изменения настроек —
no-op (диспетчер уже запущен / уже остановлен).

Wave: ``[wave:s8/k2-w2-outbox-lifecycle]``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.core.config.services.outbox import outbox_settings
from src.backend.infrastructure.messaging.outbox.dispatcher import (
    DLQHandler,
    OutboxDispatcher,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from src.backend.core.messaging.outbox import OutboxBackend, OutboxEvent

__all__ = ("start_outbox_dispatcher", "stop_outbox_dispatcher")

_logger = logging.getLogger("infrastructure.messaging.outbox.lifecycle")

_STATE_KEY = "outbox_dispatcher"


async def start_outbox_dispatcher(
    app: Any,
    *,
    backend: OutboxBackend | None = None,
    pending_source: Callable[[int], Awaitable[Sequence[OutboxEvent]]] | None = None,
    ack: Callable[[OutboxEvent], Awaitable[None]] | None = None,
    deliverer: Callable[[OutboxEvent], Awaitable[None]] | None = None,
    dlq: DLQHandler | None = None,
) -> None:
    """Lifespan startup-hook: запускает [OutboxDispatcher].

    Args:
        app: FastAPI/ASGI app или произвольный объект с ``.state``
            namespace (см. ``app_state_singleton``-паттерн V15).
        backend: [OutboxBackend] для DLQ-handoff. При ``None`` — извлекается
            из ``app.state.outbox_backend`` (если есть).
        pending_source: коллабль пуллер pending событий.
        ack: коллабль подтверждения доставки.
        deliverer: коллабль доставки в транспорт.
        dlq: опциональный явный DLQ-handler.

    При ``outbox_settings.enabled=False`` — no-op. При повторном вызове
    (диспетчер уже в state) — также no-op.
    """
    if not outbox_settings.enabled:
        _logger.info("outbox.lifecycle.disabled")
        return
    state = _resolve_state(app)
    if state is None:
        _logger.warning("outbox.lifecycle.no_state_namespace")
        return
    if getattr(state, _STATE_KEY, None) is not None:
        _logger.debug("outbox.lifecycle.already_started")
        return
    # Минимально-обязательные зависимости для диспетчера.
    if backend is None:
        backend = getattr(state, "outbox_backend", None)
    missing = [
        name
        for name, value in (
            ("backend", backend),
            ("pending_source", pending_source),
            ("ack", ack),
            ("deliverer", deliverer),
        )
        if value is None
    ]
    if missing:
        _logger.warning(
            "outbox.lifecycle.missing_dependencies", extra={"missing": missing}
        )
        return
    assert backend is not None
    assert pending_source is not None
    assert ack is not None
    assert deliverer is not None
    dispatcher = OutboxDispatcher(
        backend=backend,
        pending_source=pending_source,
        ack=ack,
        deliverer=deliverer,
        dlq=dlq,
        poll_interval=outbox_settings.poll_interval_seconds,
        batch_size=outbox_settings.batch_size,
        max_retries=outbox_settings.max_retries,
        retry_backoff_seconds=outbox_settings.retry_backoff_seconds,
        enabled=outbox_settings.enabled,
    )
    await dispatcher.start()
    setattr(state, _STATE_KEY, dispatcher)
    _logger.info("outbox.lifecycle.started")


async def stop_outbox_dispatcher(app: Any) -> None:
    """Lifespan shutdown-hook: graceful stop [OutboxDispatcher].

    Args:
        app: FastAPI/ASGI app или объект с ``.state``.

    Идемпотентен: если диспетчер не был запущен или уже остановлен —
    no-op.
    """
    state = _resolve_state(app)
    if state is None:
        return
    dispatcher: OutboxDispatcher | None = getattr(state, _STATE_KEY, None)
    if dispatcher is None:
        return
    await dispatcher.stop(timeout=outbox_settings.shutdown_timeout_seconds)
    try:
        setattr(state, _STATE_KEY, None)
    except AttributeError:
        # Некоторые namespace-объекты не разрешают переустановку — игнорируем.
        pass
    _logger.info("outbox.lifecycle.stopped")


def _resolve_state(app: Any) -> Any | None:
    """Возвращает ``app.state`` или сам ``app`` (для plain-namespace).

    Поддерживает три формы:

    * FastAPI/Starlette — ``app.state`` (``Starlette.State``);
    * plain SimpleNamespace / объект с произвольными атрибутами;
    * ``None`` — fallback при отсутствии namespace.
    """
    if app is None:
        return None
    state = getattr(app, "state", None)
    if state is not None:
        return state
    # Для plain-namespace-style объектов используем сам app.
    return app
