"""Protocol ``ExpressDialogStore`` + DTO (Wave 9.2.4).

Хранит историю переписки Express-бота: documents-per-session,
``messages`` — append-only список. TTL-индекс по полю ``ttl``
(абсолютная дата истечения, по умолчанию created_at + 30 дней).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.backend.core.models.express import ExpressDialog, ExpressMessage

__all__ = ("ExpressMessage", "ExpressDialog", "ExpressDialogStore")


@runtime_checkable
class ExpressDialogStore(Protocol):
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
    ) -> None: ...

    async def get_by_session(self, session_id: str) -> ExpressDialog | None: ...

    async def list_by_chat(
        self, group_chat_id: str, limit: int = 100
    ) -> list[ExpressDialog]: ...

    async def update_context(
        self, session_id: str, context_delta: dict[str, Any]
    ) -> None: ...

    async def ensure_indexes(self) -> None: ...
