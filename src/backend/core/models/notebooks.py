"""DTO Notebook (Wave 9.1).

Pydantic-модели Notebook и NotebookVersion — хранилище-агностичны,
одинаковая форма для in-memory и MongoDB. Версионирование — append-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("Notebook", "NotebookVersion")


def _utc_now() -> datetime:
    """Текущий момент в UTC (tz-aware)."""
    return datetime.now(timezone.utc)


class NotebookVersion(BaseModel):
    """Одна версия notebook'а в append-only истории."""

    version: int
    content: str
    changed_at: datetime = Field(default_factory=_utc_now)
    changed_by: str
    summary: str | None = None


class Notebook(BaseModel):
    """Документ заметки с историей версий и мягким удалением."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    tags: list[str] = Field(default_factory=list)
    latest_version: int = 0
    created_by: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    is_deleted: bool = False
    versions: list[NotebookVersion] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def current_content(self) -> str:
        """Контент актуальной версии или пустая строка для пустого notebook'а."""
        if not self.versions:
            return ""
        return self.versions[-1].content
