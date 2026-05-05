"""W23 — Адаптер :class:`Source` → :class:`Invoker`.

Source ничего не знает про Invoker. Адаптер — единственное место, где
``SourceEvent`` транслируется в ``InvocationRequest`` и пушится в Invoker
(W22). Заодно применяется dedup-helper по ``event_id``.

Создаётся в composition root по одному адаптеру на пару
(``source``, ``action``); ``handle`` подставляется в ``Source.start``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
)

if TYPE_CHECKING:
    from src.core.interfaces.invoker import Invoker
    from src.core.interfaces.source import SourceEvent
    from src.services.sources.idempotency import DedupeStore

PayloadMapper = Callable[["SourceEvent"], dict[str, object]]

__all__ = ("SourceToInvokerAdapter",)

logger = logging.getLogger("services.sources.adapter")


class SourceToInvokerAdapter:
    """Транслирует :class:`SourceEvent` → :class:`InvocationRequest`.

    Args:
        invoker: Singleton :class:`Invoker` из app.state.
        action: Имя action (resolved через ActionDispatcher).
        mode: Режим вызова Invoker (default — ``SYNC``).
        dedupe: Опциональный :class:`DedupeStore`. При наличии дубль по
            ``event_id`` отбрасывается без вызова Invoker.
        reply_channel: Канал ответа для асинхронных режимов
            (``InvocationMode != SYNC``).
        payload_mapper: Опциональная функция трансформации
            ``event.payload`` перед передачей в Invoker.
    """

    def __init__(
        self,
        invoker: Invoker,
        action: str,
        *,
        mode: InvocationMode = InvocationMode.SYNC,
        dedupe: DedupeStore | None = None,
        reply_channel: str | None = None,
        payload_mapper: PayloadMapper | None = None,
    ) -> None:
        self._invoker = invoker
        self._action = action
        self._mode = mode
        self._dedupe = dedupe
        self._reply_channel = reply_channel
        self._mapper = payload_mapper

    async def handle(self, event: SourceEvent) -> InvocationResponse | None:
        """Callback для :meth:`Source.start`.

        Returns:
            ``InvocationResponse`` от Invoker; ``None`` если событие
            отброшено как дубль.
        """
        if self._dedupe is not None:
            namespace = f"{event.kind.value}:{event.source_id}"
            if await self._dedupe.is_duplicate(namespace, event.event_id):
                logger.debug(
                    "SourceToInvoker: duplicate event_id=%s (source=%s) — skip",
                    event.event_id,
                    event.source_id,
                )
                return None

        payload: dict[str, object]
        if self._mapper is not None:
            payload = dict(self._mapper(event))
        else:
            # Default: payload как есть + минимум метаданных.
            payload = {
                "data": event.payload,
                "source_id": event.source_id,
                "source_kind": event.kind.value,
                "event_time": event.event_time.isoformat(),
                "event_id": event.event_id,
                **event.metadata,
            }

        request = InvocationRequest(
            action=self._action,
            payload=payload,
            mode=self._mode,
            reply_channel=self._reply_channel,
            metadata={
                "source_id": event.source_id,
                "source_kind": event.kind.value,
                "event_id": event.event_id,
            },
        )
        try:
            return await self._invoker.invoke(request)
        except Exception as exc:
            logger.error(
                "SourceToInvoker: invoker failed action=%s source=%s event_id=%s: %s",
                self._action,
                event.source_id,
                event.event_id,
                exc,
            )
            raise
