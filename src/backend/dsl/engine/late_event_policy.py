"""W14.3 — обработка late events в DSL-процессорах.

Применение :class:`LatePolicy` к одному ``Exchange``:

* ``DROP`` — пометить exchange как `_late_dropped` и не пропускать дальше.
* ``SIDE_OUTPUT`` — публикация в side-sink (callable / ReplyChannel name);
  exchange не отбрасывается, но помечается ``_late_routed``.
* ``REPROCESS`` — флагует exchange ``_late_reprocess``; downstream-процессор
  обязан реализовать compensate-логику.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from src.backend.core.types.watermark import LatePolicy, WatermarkState
from src.backend.dsl.engine.exchange import Exchange

__all__ = ("apply_late_policy",)

logger = logging.getLogger("dsl.watermark.late")

SideOutputCallable = Callable[[Exchange[Any]], Awaitable[None] | None]


async def apply_late_policy(
    exchange: Exchange[Any],
    *,
    state: WatermarkState,
    policy: LatePolicy,
    side_output: SideOutputCallable | None = None,
) -> bool:
    """Применить политику ``policy`` к late event.

    Возвращает ``True`` если exchange всё ещё пригоден для downstream
    (``SIDE_OUTPUT``/``REPROCESS``), ``False`` — если отброшен (``DROP``).

    Args:
        exchange: Текущий обмен.
        state: Состояние watermark (для метрики).
        policy: Что делать.
        side_output: Callable для ``SIDE_OUTPUT``-режима (опц.).

    Returns:
        ``True`` если exchange нужно продолжать, ``False`` если drop.
    """
    state.late_events_total += 1
    match policy:
        case LatePolicy.DROP:
            exchange.properties["_late_dropped"] = True
            logger.warning(
                "Late event dropped: exchange_id=%s", exchange.meta.exchange_id
            )
            return False
        case LatePolicy.SIDE_OUTPUT:
            exchange.properties["_late_routed"] = True
            if side_output is not None:
                try:
                    result = side_output(exchange)
                    if hasattr(result, "__await__"):
                        await result  # type: ignore[misc]
                except Exception as exc:
                    logger.error("Late side-output failed: %s", exc)
            return True
        case LatePolicy.REPROCESS:
            exchange.properties["_late_reprocess"] = True
            return True
