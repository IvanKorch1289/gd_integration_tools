"""Persistence layer для ``DegradationManager`` (S13 K2 W4).

Хранит текущий :class:`DegradationMode` + историю transitions. На production
рекомендуется Redis-implementation; на dev_light — in-memory fallback.

API:

* :meth:`persist` — записать текущий mode + transition;
* :meth:`load_current` — восстановить текущий mode при startup;
* :meth:`load_history` — последние N transitions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.backend.core.resilience.degradation import (
        DegradationMode,
        DegradationTransition,
    )

__all__ = (
    "DegradationStateStore",
    "InMemoryDegradationStateStore",
    "RedisDegradationStateStore",
)


class DegradationStateStore(Protocol):
    """Контракт для persistence-слоя."""

    async def persist(
        self, mode: DegradationMode, transition: DegradationTransition
    ) -> None:
        """Persist degradation state.

        Args:
            mode: Current degradation mode.
            transition: Transition to record.
        """
        ...

    async def load_current(self) -> DegradationMode | None:
        """Load current degradation mode.

        Returns:
            Current mode or None if not persisted.
        """
        ...

    async def load_history(self, n: int = 20) -> list[DegradationTransition]:
        """Load recent transition history.

        Args:
            n: Number of recent transitions to load.

        Returns:
            List of transitions.
        """
        ...


class InMemoryDegradationStateStore:
    """In-memory implementation для dev_light/тестов."""

    def __init__(self) -> None:
        self._current: DegradationMode | None = None
        self._history: list[DegradationTransition] = []

    async def persist(
        self, mode: DegradationMode, transition: DegradationTransition
    ) -> None:
        self._current = mode
        self._history.append(transition)
        if len(self._history) > 100:
            self._history.pop(0)

    async def load_current(self) -> DegradationMode | None:
        return self._current

    async def load_history(self, n: int = 20) -> list[DegradationTransition]:
        return self._history[-n:]


class RedisDegradationStateStore:
    """Redis-backed implementation для production.

    Schema:

    * ``degradation:current_mode`` — value: режим как строка;
    * ``degradation:history`` — LIST из JSON-сериализованных transitions.
    """

    KEY_CURRENT = "degradation:current_mode"
    KEY_HISTORY = "degradation:history"

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def persist(
        self, mode: DegradationMode, transition: DegradationTransition
    ) -> None:
        import json
        from dataclasses import asdict

        await self._redis.set(self.KEY_CURRENT, mode.value)
        await self._redis.lpush(self.KEY_HISTORY, json.dumps(asdict(transition)))
        await self._redis.ltrim(self.KEY_HISTORY, 0, 99)

    async def load_current(self) -> DegradationMode | None:
        from src.backend.core.resilience.degradation import DegradationMode

        raw = await self._redis.get(self.KEY_CURRENT)
        if raw is None:
            return None
        try:
            return DegradationMode(raw.decode() if isinstance(raw, bytes) else raw)
        except ValueError:
            return None

    async def load_history(self, n: int = 20) -> list[DegradationTransition]:
        import json

        from src.backend.core.resilience.degradation import DegradationTransition

        raw_items = await self._redis.lrange(self.KEY_HISTORY, 0, n - 1)
        result: list[DegradationTransition] = []
        for raw in raw_items:
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                data = json.loads(raw)
                result.append(DegradationTransition(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return result
