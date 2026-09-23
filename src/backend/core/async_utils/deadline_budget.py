"""DeadlineBudget — propagation единого timeout через pipeline (Sprint 12 — audit 2026-09-22 P0).

Контекст
--------
Сейчас timeout задаётся локально: middleware, processor, action handler
каждый имеют свой. Retry внутри processor может занять больше времени,
чем осталось у клиента. Параллельные ветви (parallel, saga compensation)
получают независимый полный timeout вместо доли общего бюджета.

Решение: единый :class:`DeadlineBudget`, создаваемый на входе и уменьшаемый
по мере прохождения pipeline. ``remaining()`` возвращает то, что осталось;
``asyncio_timeout()`` интегрируется со штатным ``asyncio.timeout()``.

Принципы
--------
1. **Monotonic clock** — :func:`time.monotonic` устойчив к скачкам системного
   времени (NTP, DST).
2. **Frozen + slots** — неизменяемый после создания, чтобы случайно не
   «продлить» бюджет по ошибке. ``share()`` возвращает новый объект с
   уменьшенным remaining.
3. **Fail-closed** — отрицательный или нулевой budget трактуется как
   «время вышло» (``is_expired() == True``).
4. **Compatible with asyncio.timeout** — :meth:`asyncio_timeout` возвращает
   context manager, который raises ``TimeoutError`` сразу, если budget
   уже исчерпан (``asyncio.wait_for`` подождёт первого ``await``, что
   может затянуть).

Использование
-------------
::

    from src.backend.core.async_utils.deadline_budget import DeadlineBudget

    budget = DeadlineBudget.from_timeout(timeout=30.0)
    async with budget.asyncio_timeout():
        await do_work()  # bounded by remaining budget

    # Sub-budget для parallel-ветки:
    sub = budget.split(0.5)  # 50% от remaining
    if sub.is_expired():
        raise DeadlineExpiredError("not enough budget for this branch")
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Self

logger = logging.getLogger(__name__)

__all__ = ("DeadlineBudget", "DeadlineExpiredError", "DeadlineOverflowError")


class DeadlineExpiredError(asyncio.TimeoutError):
    """DeadlineBudget исчерпан до или в момент вызова.

    Наследуется от :class:`asyncio.TimeoutError` для backward-compat
    с ``except TimeoutError``, но имеет конкретный type для диагностики
    и метрик (path, original_budget).
    """

    def __init__(
        self, message: str, *, path: str = "", original_timeout: float | None = None
    ) -> None:
        super().__init__(message)
        self.path = path
        self.original_timeout = original_timeout


class DeadlineOverflowError(ValueError):
    """Некорректное значение timeout при создании бюджета.

    Не наследуется от TimeoutError — это программная ошибка
    (timeout должен быть положительным float).
    """


@dataclass(frozen=True, slots=True)
class DeadlineBudget:
    """Единый бюджет времени на обработку запроса / pipeline ветки.

    Attributes:
        deadline_ts: абсолютный монотонный timestamp, к которому бюджет
            истекает (``time.monotonic()``).
        original_timeout: исходный timeout в секундах при создании —
            хранится для diagnostics, логирования и метрик.

    Note:
        Не пытайтесь модифицировать ``deadline_ts`` после создания —
        объект frozen. Для sub-budget используйте :meth:`share` или
        :meth:`split`, которые возвращают новый объект с уменьшенным
        effective deadline.
    """

    deadline_ts: float
    original_timeout: float

    @classmethod
    def from_timeout(cls, timeout: float, *, now: float | None = None) -> Self:
        """Создать DeadlineBudget с заданным timeout в секундах.

        Args:
            timeout: положительное число секунд. ``0`` или отрицательное —
                :class:`DeadlineOverflowError` (явная ошибка конфигурации,
                не «время вышло»).
            now: переопределить монотонное время (для тестов).

        Returns:
            Новый DeadlineBudget с ``deadline_ts = now + timeout``.

        Raises:
            DeadlineOverflowError: если ``timeout`` не положительный.
        """
        if (
            timeout <= 0 or timeout != timeout or math.isinf(timeout)
        ):  # reject 0/neg/NaN/inf
            raise DeadlineOverflowError(
                f"timeout must be positive finite seconds, got {timeout!r}"
            )
        base = now if now is not None else time.monotonic()
        return cls(deadline_ts=base + timeout, original_timeout=timeout)

    def remaining(self, *, now: float | None = None) -> float:
        """Оставшееся время в секундах.

        Возвращает ``0.0``, если бюджет исчерпан. Никогда не отрицательное.
        """
        base = now if now is not None else time.monotonic()
        diff = self.deadline_ts - base
        return max(0.0, diff)

    def is_expired(self, *, now: float | None = None) -> bool:
        """Бюджет исчерпан (включая случай, когда изначально был 0)."""
        return self.remaining(now=now) <= 0.0

    def share(self, fraction: float) -> Self:
        """Sub-budget с fraction от текущего remaining.

        Используется для parallel-ветвей и saga compensation:
        каждый ребёнок получает свою долю от parent budget.

        Args:
            fraction: доля [0.0, 1.0]. 0 = нулевой budget (сразу истёкший),
                1 = полная копия.

        Returns:
            Новый DeadlineBudget с deadline = now + remaining * fraction.

        Raises:
            DeadlineOverflowError: fraction вне [0.0, 1.0] или NaN.
        """
        if fraction < 0.0 or fraction > 1.0 or fraction != fraction:
            raise DeadlineOverflowError(
                f"fraction must be in [0.0, 1.0], got {fraction!r}"
            )
        remaining = self.remaining()
        # Округление до микросекунд для стабильности parent/child budgets.
        sub_remaining = round(remaining * fraction, 6)
        return type(self)(
            deadline_ts=time.monotonic() + sub_remaining,
            original_timeout=round(self.original_timeout * fraction, 6),
        )

    def split(self, fraction: float) -> Self:
        """Alias для :meth:`share` — alternative name, более явный в parallel-контексте.

        См. :meth:`share` для семантики.
        """
        return self.share(fraction)

    def asyncio_timeout(self) -> "_DeadlineBudgetTimeoutCM":
        """Context manager, совместимый с ``asyncio.timeout``.

        Поведение:
            * Если budget уже исчерпан — raises :class:`DeadlineExpiredError`
              СРАЗУ при входе (без ожидания первого ``await``).
            * Иначе — делегирует ``asyncio.timeout(remaining())``.

        Note:
            ``asyncio.timeout`` сам по себе НЕ режет на ``remaining()``,
            а использует значение на момент входа в CM. Это означает,
            что долгий CPU-bound блок внутри CM не увидит обновления.
            Для долгих операций периодически вызывайте :meth:`remaining`
            вручную или используйте :meth:`wait_for` helper.
        """
        remaining = self.remaining()
        if remaining <= 0.0:
            raise DeadlineExpiredError(
                "deadline already expired at context entry",
                original_timeout=self.original_timeout,
            )
        # ``asyncio.timeout`` value: оставшееся время сейчас.
        # Возвращаем wrapper, а не CM-as-generator (asyncio.timeout не
        # реализует __enter__/__exit__ как generator-based CM).
        return _DeadlineBudgetTimeoutCM(asyncio.timeout(remaining), self)


class _DeadlineBudgetTimeoutCM:
    """Async context manager — обёртка над :class:`asyncio.Timeout` с diagnostics.

    Используется как ``async with budget.asyncio_timeout():``.
    """

    def __init__(self, inner_cm: asyncio.Timeout, budget: DeadlineBudget) -> None:
        self._inner_cm = inner_cm
        self._budget = budget

    async def __aenter__(self) -> Self:
        await self._inner_cm.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Делегируем ``asyncio.Timeout.__aexit__``, перехватывая TimeoutError.

        В Python 3.14 ``asyncio.Timeout.__aexit__`` сам поднимает
        ``TimeoutError`` при превышении. Перехватываем его и заменяем на
        :class:`DeadlineExpiredError` с метаданными budget для лучшей
        диагностики и метрик (path/original_timeout).
        """
        try:
            await self._inner_cm.__aexit__(exc_type, exc_val, exc_tb)
        except asyncio.TimeoutError as e:
            raise DeadlineExpiredError(
                f"deadline exceeded ({self._budget.original_timeout}s budget)",
                original_timeout=self._budget.original_timeout,
            ) from e
        # Если __aexit__ НЕ поднял (например, истекло вне await-секции),
        # проверяем тип исключения.
        if exc_type is asyncio.TimeoutError:
            raise DeadlineExpiredError(
                f"deadline exceeded ({self._budget.original_timeout}s budget)",
                original_timeout=self._budget.original_timeout,
            ) from exc_val
