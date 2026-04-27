"""Supervisor — auto-restart долгоживущих coroutine с jittered backoff (Wave 6.5).

Применение: оборачивает фабрику coroutine'ы и перезапускает её при падении
с экспоненциальным backoff'ом + jitter. Уважает graceful shutdown:
``CancelledError`` пробрасывается без рестарта.

Использование::

    sup = Supervisor(
        name="worker",
        coro_factory=lambda: _run_worker(...),
        backoff=BackoffPolicy(),
    )
    await sup.run()
"""


import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable

from src.core.config.constants import consts

__all__ = ("BackoffPolicy", "Supervisor")

logger = logging.getLogger("resilience.supervisor")


@dataclass(slots=True, frozen=True)
class BackoffPolicy:
    """Политика jittered exponential backoff между попытками рестарта.

    Дефолты — из ``core.config.constants.consts`` (общие для retry).
    """

    initial_seconds: float = consts.DEFAULT_RETRY_INITIAL_BACKOFF
    multiplier: float = consts.DEFAULT_RETRY_BACKOFF_MULTIPLIER
    max_seconds: float = 60.0
    jitter: float = consts.DEFAULT_RETRY_JITTER

    def delay_for(self, attempt: int) -> float:
        """Возвращает delay для попытки ``attempt`` (0-индексированной)."""
        base = min(
            self.initial_seconds * (self.multiplier**attempt), self.max_seconds
        )
        # secrets.SystemRandom — без cryptographic warning (S311) и достаточно
        # для jittered backoff.
        return base + secrets.SystemRandom().uniform(0.0, self.jitter)


class Supervisor:
    """Перезапускает coroutine при падении с jittered backoff."""

    def __init__(
        self,
        *,
        name: str,
        coro_factory: Callable[[], Awaitable[None]],
        backoff: BackoffPolicy | None = None,
        is_draining: Callable[[], bool] | None = None,
    ) -> None:
        self.name = name
        self._coro_factory = coro_factory
        self._backoff = backoff or BackoffPolicy()
        self._is_draining = is_draining or (lambda: False)

    async def run(self) -> None:
        """Бесконечный цикл с auto-restart, пока не дойдёт graceful drain."""
        attempt = 0
        while True:
            if self._is_draining():
                logger.info("Supervisor[%s] draining — exit loop", self.name)
                return
            try:
                await self._coro_factory()
                logger.info("Supervisor[%s] coroutine returned cleanly", self.name)
                return
            except asyncio.CancelledError:
                logger.info("Supervisor[%s] cancelled — graceful exit", self.name)
                raise
            except Exception as exc:  # noqa: BLE001
                delay = self._backoff.delay_for(attempt)
                attempt += 1
                logger.warning(
                    "Supervisor[%s] attempt #%d failed: %s — restart in %.2fs",
                    self.name,
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
