"""Bulkhead pattern — изоляция ресурсов по semaphore.

Максимум N параллельных вызовов per service — падение одного
не съедает все воркеры для других.
"""

from __future__ import annotations

import asyncio

__all__ = ("Bulkhead", "get_bulkhead")


class Bulkhead:
    """Bulkhead pattern — изоляция ресурсов через ``asyncio.Semaphore``."""

    def __init__(self) -> None:
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def register(self, service: str, max_concurrent: int = 10) -> None:
        """Register a service with max concurrent limit.

        Args:
            service: Service identifier.
            max_concurrent: Maximum concurrent calls allowed.
        """
        self._semaphores[service] = asyncio.Semaphore(max_concurrent)

    async def acquire(self, service: str, timeout: float = 30.0) -> bool:
        """Захватывает слот. Возвращает False при таймауте."""
        if service not in self._semaphores:
            self.register(service)
        sem = self._semaphores[service]
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    def release(self, service: str) -> None:
        """Release a semaphore slot for a service.

        Args:
            service: Service identifier.
        """
        if service in self._semaphores:
            self._semaphores[service].release()

    def stats(self) -> dict[str, dict[str, int]]:
        """Get statistics for all registered services.

        Returns:
            Dict mapping service names to their semaphore stats.
        """
        return {
            name: {"available": sem._value, "locked": sem.locked()}
            for name, sem in self._semaphores.items()
        }


_bulkhead: Bulkhead | None = None


def get_bulkhead() -> Bulkhead:
    """Singleton-аксессор для глобального Bulkhead."""
    global _bulkhead
    if _bulkhead is None:
        _bulkhead = Bulkhead()
    return _bulkhead
