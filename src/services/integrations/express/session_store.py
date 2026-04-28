"""Protocol ``ExpressSessionStore`` + DTO (Wave 9.2.4).

Сессии Express-бота. TTL-индекс по ``last_activity_at`` (1 час
неактивности → авто-удаление).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("ExpressSession", "ExpressSessionStore")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExpressSession(BaseModel):
    """Документ сессии Express-бота."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    bot_id: str
    context: dict[str, Any] = Field(default_factory=dict)
    state: str = "active"
    created_at: datetime = Field(default_factory=_utc_now)
    last_activity_at: datetime = Field(default_factory=_utc_now)


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
