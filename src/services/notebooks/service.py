"""``NotebookService`` — фасад над ``NotebookRepository`` (Wave 9.1).

Бизнес-логика: создание, обновление контента (append-version), restore,
list, soft-delete. Конкретный backend (in-memory / Mongo) подменяется
через DI в ``_default_repository_factory``.
"""

from __future__ import annotations

import logging
from typing import Any

from src.infrastructure.application.di import app_state_singleton
from src.services.notebooks.models import Notebook, NotebookVersion
from src.services.notebooks.repository import (
    InMemoryNotebookRepository,
    NotebookRepository,
)

__all__ = ("NotebookService", "get_notebook_service")

logger = logging.getLogger(__name__)


class NotebookService:
    """Бизнес-логика поверх ``NotebookRepository``."""

    def __init__(self, repository: NotebookRepository) -> None:
        self._repo = repository

    async def ensure_indexes(self) -> None:
        await self._repo.ensure_indexes()

    async def create(
        self,
        *,
        title: str,
        content: str,
        created_by: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Notebook:
        notebook = Notebook(
            title=title,
            tags=list(tags or []),
            created_by=created_by,
            metadata=dict(metadata or {}),
        )
        if content:
            notebook.versions.append(
                NotebookVersion(version=1, content=content, changed_by=created_by)
            )
            notebook.latest_version = 1
        await self._repo.create(notebook)
        return notebook

    async def get(self, notebook_id: str) -> Notebook | None:
        return await self._repo.get(notebook_id)

    async def get_version(
        self, notebook_id: str, version: int
    ) -> NotebookVersion | None:
        notebook = await self._repo.get(notebook_id)
        if notebook is None:
            return None
        return next((v for v in notebook.versions if v.version == version), None)

    async def list_versions(self, notebook_id: str) -> list[NotebookVersion]:
        notebook = await self._repo.get(notebook_id)
        if notebook is None:
            return []
        return list(notebook.versions)

    async def update_content(
        self, *, notebook_id: str, content: str, user: str, summary: str | None = None
    ) -> Notebook | None:
        return await self._repo.append_version(notebook_id, content, user, summary)

    async def restore_version(
        self, *, notebook_id: str, version: int, user: str
    ) -> Notebook | None:
        return await self._repo.restore_version(notebook_id, version, user)

    async def list_all(
        self,
        *,
        tag: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Notebook]:
        return await self._repo.list_all(
            tag=tag, include_deleted=include_deleted, limit=limit, offset=offset
        )

    async def delete(self, notebook_id: str) -> bool:
        return await self._repo.soft_delete(notebook_id)


def _default_repository_factory() -> NotebookRepository:
    """Возвращает MongoNotebookRepository, fallback на InMemory."""
    try:
        from src.infrastructure.repositories.notebooks_mongo import (
            MongoNotebookRepository,
        )

        return MongoNotebookRepository()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "MongoNotebookRepository недоступен (fallback InMemory): %s", exc
        )
        return InMemoryNotebookRepository()


def _default_service_factory() -> NotebookService:
    return NotebookService(_default_repository_factory())


@app_state_singleton("notebook_service", factory=_default_service_factory)
def get_notebook_service() -> NotebookService:
    """Singleton ``NotebookService``. Backend подменяется через app.state."""
