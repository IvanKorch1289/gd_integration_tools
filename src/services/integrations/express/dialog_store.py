"""Protocol ``ExpressDialogStore`` + DTO (Wave 9.2.4).

Хранит историю переписки Express-бота: documents-per-session,
``messages`` — append-only список. TTL-индекс по полю ``ttl``
(абсолютная дата истечения, по умолчанию created_at + 30 дней).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("ExpressMessage", "ExpressDialog", "ExpressDialogStore")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExpressMessage(BaseModel):
    """Одно сообщение в диалоге."""

    model_config = ConfigDict(extra="ignore")

    role: str  # "user" | "bot"
    body: str
    sync_id: str | None = None
    ts: datetime = Field(default_factory=_utc_now)
    bubble: dict[str, Any] | None = None
    keyboard: dict[str, Any] | None = None


class ExpressDialog(BaseModel):
    """Документ диалога (один на сессию)."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    bot_id: str
    group_chat_id: str
    user_huid: str | None = None
    messages: list[ExpressMessage] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    state: str = "active"
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    ttl: datetime | None = None


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
