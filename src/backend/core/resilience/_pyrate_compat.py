"""pyrate_limiter compatibility helpers.

Sprint 1 V16 Single-Entry (Step 3.4):

* :func:`shutdown_pyrate_leaker` — graceful cancel фоновой
  ``Leaker.aio_leak_task``, которая стартует при первом async-операции
  Limiter'а. Без явного cancel'а task оставляет hanging-future в event
  loop и не даёт ASGI-stack'у завершиться (V15 R-V15-11 leak prevention).
  Изначально hook был inline в ``plugins/composition/lifecycle.py``,
  Step 3.4 вынес его сюда.

* :class:`BoundedInMemoryBucket` — расширение ``InMemoryBucket`` с
  жёстким ограничением размера ``items``-буфера и LRU-eviction. Защита
  от unbounded growth при per-IP / per-tenant rate-limiting'е, где
  каждый новый identifier мог бы наращивать локальное состояние без
  верхней границы.

Параметры по умолчанию:

* ``max_items=10_000`` — выше типичного rate.limit на порядки, но ниже
  разумного process-memory budget'а.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pyrate_limiter import InMemoryBucket, Rate

if TYPE_CHECKING:
    from pyrate_limiter import Limiter
    from pyrate_limiter.abstracts.rate import RateItem


__all__ = ("BoundedInMemoryBucket", "shutdown_pyrate_leaker")

_logger = logging.getLogger("resilience.pyrate_compat")


async def shutdown_pyrate_leaker(limiter: "Limiter") -> None:
    """Останавливает фоновую ``Leaker.aio_leak_task`` указанного Limiter'а.

    Вызывается из application shutdown hook. Безопасен к повторному
    вызову — отсутствие task'а или его завершённое состояние не
    расцениваются как ошибка.

    Args:
        limiter: pyrate ``Limiter`` (singleton из
            ``entrypoints/dependencies/rate_limit.py::get_default_limiter``
            или любой другой инстанс).
    """
    leaker = getattr(limiter, "_leaker", None) or getattr(
        getattr(limiter, "bucket_factory", None), "_leaker", None
    )
    if leaker is None:
        return
    leak_task = getattr(leaker, "aio_leak_task", None)
    if leak_task is None or leak_task.done():
        return

    leak_task.cancel()
    try:
        await leak_task
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001
        _logger.debug("pyrate Leaker join error: %s", exc)


class BoundedInMemoryBucket(InMemoryBucket):
    """``InMemoryBucket`` с жёстким cap'ом на размер items-буфера.

    Базовый ``InMemoryBucket`` хранит RateItem'ы в обычном списке и сам
    вычищает их при ``leak()`` (по самому большому ``rate.interval``).
    В hot-path с тысячами identifier'ов между leak'ами список может
    кратко превысить ``max_items`` — это защита от unbounded growth.

    При превышении лимита сбрасывается ``oldest`` items (LRU по
    timestamp — items в pyrate уже отсортированы по времени вставки).

    Args:
        rates: Список ``Rate`` (передаётся в ``InMemoryBucket``).
        max_items: Жёсткий потолок ``len(items)``. Default ``10_000``.
    """

    def __init__(self, rates: list[Rate], *, max_items: int = 10_000) -> None:
        super().__init__(rates)
        self.max_items = max_items

    def put(self, item: "RateItem") -> bool:
        """Прокси к ``InMemoryBucket.put`` с post-trim до ``max_items``."""
        accepted = super().put(item)
        if accepted and len(self.items) > self.max_items:
            overflow = len(self.items) - self.max_items
            del self.items[:overflow]
            _logger.warning(
                "BoundedInMemoryBucket overflow: trimmed %d oldest items "
                "(max_items=%d)",
                overflow,
                self.max_items,
            )
        return accepted

    def stats(self) -> dict[str, Any]:
        """Snapshot для health-aggregator'а."""
        return {
            "items": len(self.items),
            "max_items": self.max_items,
            "saturation": len(self.items) / self.max_items if self.max_items else 0.0,
        }
