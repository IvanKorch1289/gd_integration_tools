"""HealthAdapter — bridges legacy health()->bool objects to InfrastructureClient SPI.

Позволяет регистрировать sources/sinks/storage backends в ConnectorRegistry
без модификации их кода. Адаптер вызывает существующий health()/healthcheck()
и оборачивает результат в HealthResult с timing.
"""

from __future__ import annotations

from typing import Any

from src.backend.infrastructure.clients.base_connector import (
    HealthMode,
    HealthResult,
    InfrastructureClient,
)

__all__ = ("HealthAdapter",)


class HealthAdapter(InfrastructureClient):
    """Adapts legacy objects (health()->bool / healthcheck()->bool) к InfrastructureClient.

    * ``start``/``stop`` — idempotent no-ops (lifecycle управляется источником).
    * ``health(mode)`` — вызывает legacy-метод и оборачивает в HealthResult.
    """

    def __init__(self, name: str, target: Any) -> None:
        super().__init__(name=name)
        self._target = target

    async def start(self) -> None:
        """Метод start (см. signature)."""
        self._started = True

    async def stop(self) -> None:
        """Метод stop (см. signature)."""
        self._started = False

    async def health(self, mode: HealthMode = "fast") -> HealthResult:
        """Метод health (см. signature)."""
        fn = (
            getattr(self._target, "health", None)
            or getattr(self._target, "healthcheck", None)
            or getattr(self._target, "health_check", None)
        )
        if fn is None:
            return HealthResult.failed(error="No health method", mode=mode)

        # ponytail: legacy-методы возвращают bool (True=ok, False=failed).
        # ``_timed_health`` отличает failure только по exception, поэтому
        # оборачиваем fn в probe, который транслирует falsy bool в ошибку;
        # dict-ответ (расширенный health) пропускаем как details.
        async def _probe() -> dict[str, Any]:
            raw = await fn() if callable(fn) else fn
            if isinstance(raw, bool):
                if not raw:
                    raise RuntimeError("legacy health() returned False")
                return {}
            return raw if isinstance(raw, dict) else {}

        return await self._timed_health(_probe, mode)
