"""DTO Express-bot (Wave 9.2.4).

История переписки и сессии Express-бота — хранилище-агностичные
Pydantic-модели для in-memory и MongoDB-репозиториев.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("ExpressDialog", "ExpressMessage", "ExpressSession")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExpressMessage(BaseModel):
    """Одно сообщение в диалоге."""

    model_config = ConfigDict(extra="ignore")

    role: str
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


class ExpressSession(BaseModel):
    """Документ сессии Express-бота."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    bot_id: str
    context: dict[str, Any] = Field(default_factory=dict)
    state: str = "active"
    created_at: datetime = Field(default_factory=_utc_now)
    last_activity_at: datetime = Field(default_factory=_utc_now)
