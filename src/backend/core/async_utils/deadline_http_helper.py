"""HTTP-timeout helper for ``DeadlineBudget`` (Sprint 12 — audit 2026-09-22 P0).

Проблема:
    ``httpx``, ``aiohttp`` и другие async HTTP clients принимают ``timeout``
    как ``float`` (общий timeout) или ``httpx.Timeout`` (детальные таймауты).
    Если задать локальный фиксированный timeout, внутренние retry могут
    занять больше, чем осталось в client deadline → ``CancelledError``
    прилетает после того, как клиент уже отключился.

Решение:
    :func:`http_timeout_from_deadline` возвращает ``float | None`` —
    сколько секунд осталось в ``DeadlineBudget`` (или ``None``, если
    deadline уже истёк / не установлен).

Использование в HTTP-вызовах::

    from src.backend.core.async_utils.deadline_http_helper import (
        http_timeout_from_deadline,
    )

    timeout = http_timeout_from_deadline()
    if timeout is None:
        raise DeadlineExpiredError("client deadline exhausted")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)

Note:
    Это helper только для **outbound** HTTP. Для inbound (request handling)
    используется ``TimeoutMiddleware`` × ``DeadlineBudget`` integration.
"""

from __future__ import annotations

import logging

from src.backend.core.async_utils.deadline_budget import DeadlineExpiredError

logger = logging.getLogger(__name__)

__all__ = ("http_timeout_from_deadline", "DeadlineExpiredError")


def http_timeout_from_deadline(*, floor: float = 0.0) -> float | None:
    """Получить remaining seconds из ``DeadlineBudget`` для HTTP timeout.

    Args:
        floor: минимальное значение timeout (если remaining меньше floor,
            вернуть ``floor``; полезно для connect-timeout, чтобы не
            падать до 0 при активном deadline).

    Returns:
        Оставшиеся секунды (``floor <= value <= remaining``) или ``None``,
        если:
        - ``RequestContext.deadline_budget`` не установлен;
        - deadline уже истёк (``is_expired()``);
        - произошла ошибка при чтении ``RequestContext.current()``.

    Логика:
        - ``None`` означает «не вызывать downstream» (admission control).
        - ``floor=0.0`` (default) → return ``0.0`` для истёкшего budget,
          чтобы ``httpx.Timeout(0)`` корректно поднимал TimeoutError.
        - ``floor > 0`` → минимальный positive timeout, даже если budget истёк.

    Note:
        Все ошибки проглатываются (graceful degradation): если
        ``RequestContext`` недоступен (например, в CLI-режиме), возвращается
        ``None``, и caller решает, использовать default timeout или нет.
    """
    try:
        from src.backend.core.request_context import RequestContext

        ctx = RequestContext.current()
        if ctx is None or ctx.deadline_budget is None:
            return None
        remaining = ctx.deadline_budget.remaining()
        if remaining <= 0.0:
            return floor
        # ``floor`` может быть только нижней границей; remaining > floor.
        return max(floor, remaining)
    except Exception as e:
        # Graceful degradation: если что-то пошло не так (например,
        # deadline_budget имеет неожиданный тип), логируем и возвращаем None.
        logger.debug("http_timeout_from_deadline: %s", e)
        return None
