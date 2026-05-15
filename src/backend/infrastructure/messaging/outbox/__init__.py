"""Outbox dispatcher (L-scope) — production-backend для [OutboxBackend] Protocol.

Пакет содержит:

* :class:`OutboxDispatcher` — periodic polling + delivery + tenacity-retry +
  DLQ-handoff в один цикл.
* :class:`DLQHandler` — типовой Protocol-обёртка для DLQ-handoff (по
  умолчанию ``OutboxBackend.enqueue`` с ``status=DLQ``).
* :mod:`lifecycle` — async lifespan hooks (start/stop), которые позднее
  подключит координатор в ``plugins/composition/lifecycle.py``.

Контракт `OutboxBackend` (см. ``core/messaging/outbox.py``) описывает
DLQ-store API; dispatcher использует его для handoff неуспешно
доставленных событий через ``enqueue`` с ``status=DLQ``.

Wave: ``[wave:s8/k2-w2-outbox-dispatcher]``.
"""

from __future__ import annotations

from src.backend.infrastructure.messaging.outbox.dispatcher import (
    DLQHandler,
    OutboxDispatcher,
)

__all__ = (
    "DLQHandler",
    "OutboxDispatcher",
)
