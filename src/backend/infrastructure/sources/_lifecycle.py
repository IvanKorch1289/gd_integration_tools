"""W23 — общие helper'ы жизненного цикла Source.

Выносит повторяющийся код graceful-cancel задачи: при ``stop()`` мы
отменяем asyncio.Task и игнорируем ``CancelledError``, но любую другую
ошибку логируем (вместо глотания).
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("infrastructure.sources.lifecycle")

__all__ = ("graceful_cancel",)


async def graceful_cancel(task: asyncio.Task[object] | None, *, source_id: str) -> None:
    """Отменить задачу и дождаться завершения, не пропуская ошибок.

    Args:
        task: Задача (или None — no-op).
        source_id: Имя источника для лога ошибок.
    """
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.warning("Source %s: ошибка при graceful stop: %s", source_id, exc)
