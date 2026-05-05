"""Protocol ``ExpressSessionStore`` + DTO (Wave 9.2.4).

Сессии Express-бота. TTL-индекс по ``last_activity_at`` (1 час
неактивности → авто-удаление).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.core.models.express import ExpressSession

__all__ = ("ExpressSession", "ExpressSessionStore")


@runtime_checkable
class ExpressSessionStore(Protocol):
    async def create(
        self, bot_id: str, *, initial_context: dict[str, Any] | None = None
    ) -> str: ...

    async def get(self, session_id: str) -> ExpressSession | None: ...

    async def update_context(
        self, session_id: str, context_delta: dict[str, Any]
    ) -> None: ...

    async def ping(self, session_id: str) -> None: ...

    async def ensure_indexes(self) -> None: ...
