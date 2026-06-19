"""Protocol ``ExpressDialogStore`` + DTO (Wave 9.2.4).

Хранит историю переписки Express-бота: documents-per-session,
``messages`` — append-only список. TTL-индекс по полю ``ttl``
(абсолютная дата истечения, по умолчанию created_at + 30 дней).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.backend.core.models.express import ExpressDialog, ExpressMessage

__all__ = ("ExpressDialog", "ExpressDialogStore", "ExpressMessage")


@runtime_checkable
class ExpressDialogStore(Protocol):
    """Express bot dialog store contract."""

    async def append_message(
        self,
        session_id: str,
        role: str,
        body: str,
        *,
        bot_id: str | None = None,
        group_chat_id: str | None = None,
        user_huid: str | None = None,
        sync_id: str | None = None,
        bubble: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> None:
        """Append a message to dialog history.

        Args:
            session_id: Session identifier.
            role: Message role (user/bot).
            body: Message body.
            bot_id: Optional bot identifier.
            group_chat_id: Optional group chat ID.
            user_huid: Optional user HUID.
            sync_id: Optional sync ID.
            bubble: Optional bubble data.
            keyboard: Optional keyboard data.
        """
        ...

    async def get_by_session(self, session_id: str) -> ExpressDialog | None:
        """Get dialog by session ID.

        Args:
            session_id: Session identifier.

        Returns:
            ExpressDialog or None if not found.
        """
        ...

    async def list_by_chat(
        self, group_chat_id: str, limit: int = 100
    ) -> list[ExpressDialog]:
        """List dialogs by group chat.

        Args:
            group_chat_id: Group chat identifier.
            limit: Maximum results.

        Returns:
            List of ExpressDialog objects.
        """
        ...

    async def update_context(
        self, session_id: str, context_delta: dict[str, Any]
    ) -> None:
        """Update dialog context.

        Args:
            session_id: Session identifier.
            context_delta: Context fields to update.
        """
        ...

    async def ensure_indexes(self) -> None: ...
