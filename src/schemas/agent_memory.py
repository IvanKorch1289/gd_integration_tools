"""Pydantic-схемы AgentMemory REST API (Wave 8.4).

Три ресурса под общей сессией ``session_id``:

* ``messages`` — диалоговая history (TTL = short_term_ttl_seconds);
* ``scratchpad`` — singleton рабочая область сессии (TTL = long_term);
* ``facts`` — key-value факты (TTL = long_term).

Все схемы — ``ConfigDict(extra='forbid')`` для строгой валидации.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "FactCreate",
    "FactRead",
    "FactsResponse",
    "MessageCreate",
    "MessagesResponse",
    "ScratchpadResponse",
    "ScratchpadValue",
    "SessionPath",
    "SessionListQuery",
    "FactKeyPath",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionPath(_StrictModel):
    """Path-параметр session_id."""

    session_id: str = Field(..., min_length=1, description="ID сессии агента.")


class FactKeyPath(_StrictModel):
    """Path для DELETE/GET одного факта."""

    session_id: str = Field(..., min_length=1)
    fact_key: str = Field(..., min_length=1)


class SessionListQuery(_StrictModel):
    """Query для GET /messages (last_n)."""

    last_n: int = Field(default=20, ge=1, le=500)


class MessageCreate(_StrictModel):
    """POST /messages — добавить сообщение в history."""

    role: str = Field(..., description="``user`` / ``assistant`` / ``system``.")
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] | None = Field(default=None)


class MessagesResponse(_StrictModel):
    """GET /messages — список последних N сообщений (chronological)."""

    items: list[dict[str, Any]]


class ScratchpadValue(_StrictModel):
    """PUT /scratchpad — задать рабочую область."""

    content: str = Field(default="", description="Произвольный markdown/json/text.")


class ScratchpadResponse(_StrictModel):
    """GET /scratchpad."""

    session_id: str
    content: str


class FactCreate(_StrictModel):
    """POST /facts — добавить факт (key/value)."""

    fact_key: str = Field(..., min_length=1, max_length=128)
    value: str = Field(..., min_length=1)


class FactRead(_StrictModel):
    """Один факт в response."""

    fact_key: str
    value: str


class FactsResponse(_StrictModel):
    """GET /facts — все факты сессии."""

    session_id: str
    facts: list[FactRead]
