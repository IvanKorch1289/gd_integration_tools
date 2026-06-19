"""Protocol ``ExpressSessionStore`` + DTO (Wave 9.2.4).

Сессии Express-бота. TTL-индекс по ``last_activity_at`` (1 час
неактивности → авто-удаление).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.backend.core.models.express import ExpressSession

__all__ = ("ExpressSession", "ExpressSessionStore")


@runtime_checkable
class ExpressSessionStore(Protocol):
    """Express bot session store contract."""

    async def create(
        self, bot_id: str, *, initial_context: dict[str, Any] | None = None
    ) -> str:
        """Create a new session.

        Args:
            bot_id: Bot identifier.
            initial_context: Optional initial context.

        Returns:
            Session ID.
        """
        ...

    async def get(self, session_id: str) -> ExpressSession | None:
        """Get session by ID.

        Args:
            session_id: Session identifier.

        Returns:
            ExpressSession or None if not found.
        """
        ...

    async def update_context(
        self, session_id: str, context_delta: dict[str, Any]
    ) -> None:
        """Update session context.

        Args:
            session_id: Session identifier.
            context_delta: Context fields to update.
        """
        ...

    async def ping(self, session_id: str) -> None:
        """Update session last activity timestamp.

        Args:
            session_id: Session identifier.
        """
        ...

    async def ensure_indexes(self) -> None:
        """Create TTL indexes (idempotent)."""
        ...
