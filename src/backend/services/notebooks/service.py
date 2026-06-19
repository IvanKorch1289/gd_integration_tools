"""``NotebookService`` — фасад над ``NotebookRepository`` (Wave 9.1).

Бизнес-логика: создание, обновление контента (append-version), restore,
list, soft-delete. Конкретный backend (in-memory / Mongo) подменяется
через DI в ``_default_repository_factory``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.core.logging import get_logger
from src.backend.services.notebooks.models import Notebook, NotebookVersion
from src.backend.services.notebooks.repository import (
    InMemoryNotebookRepository,
    NotebookRepository,
)

__all__ = ("NotebookService", "get_notebook_service")

logger = get_logger(__name__)


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
        """Create a new notebook.

        Args:
            title: Notebook title.
            content: Initial content.
            created_by: Author name.
            tags: Optional tags.
            metadata: Optional metadata.

        Returns:
            Created notebook.
        """
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
        _trigger_rag_index(notebook)
        return notebook

    async def get(self, notebook_id: str) -> Notebook | None:
        """Get notebook by ID.

        Args:
            notebook_id: Notebook ID.

        Returns:
            Notebook or None if not found.
        """
        return await self._repo.get(notebook_id)

    async def get_version(
        self, notebook_id: str, version: int
    ) -> NotebookVersion | None:
        """Get a specific version of a notebook.

        Args:
            notebook_id: Notebook ID.
            version: Version number.

        Returns:
            NotebookVersion or None if not found.
        """
        notebook = await self._repo.get(notebook_id)
        if notebook is None:
            return None
        return next((v for v in notebook.versions if v.version == version), None)

    async def list_versions(self, notebook_id: str) -> list[NotebookVersion]:
        """List all versions of a notebook.

        Args:
            notebook_id: Notebook ID.

        Returns:
            List of NotebookVersion objects.
        """
        notebook = await self._repo.get(notebook_id)
        if notebook is None:
            return []
        return list(notebook.versions)

    async def update_content(
        self, *, notebook_id: str, content: str, user: str, summary: str | None = None
    ) -> Notebook | None:
        """Update notebook content (append new version).

        Args:
            notebook_id: Notebook ID.
            content: New content.
            user: Author name.
            summary: Optional version summary.

        Returns:
            Updated notebook or None if not found.
        """
        notebook = await self._repo.append_version(notebook_id, content, user, summary)
        if notebook is not None:
            _trigger_rag_index(notebook)
        return notebook

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
        deleted = await self._repo.soft_delete(notebook_id)
        if deleted:
            _trigger_rag_delete(notebook_id)
        return deleted


def _trigger_rag_index(notebook: Notebook) -> None:
    """Best-effort fire-and-forget индексация в RAG. Тихо игнорирует ошибки."""
    try:
        from src.backend.services.notebooks.indexer import get_notebook_indexer

        get_notebook_indexer().index_one_fire_and_forget(notebook)
    except Exception as exc:
        logger.warning("RAG-индексация notebook'а не запущена: %s", exc)


def _trigger_rag_delete(notebook_id: str) -> None:
    """Best-effort fire-and-forget удаление из RAG."""
    try:
        from src.backend.core.utils.task_registry import get_task_registry
        from src.backend.services.notebooks.indexer import get_notebook_indexer

        get_task_registry().create_task(
            get_notebook_indexer().delete_one(notebook_id),
            name=f"notebook-indexer:delete:{notebook_id}",
        )
    except Exception as exc:
        logger.warning("RAG-удаление notebook'а %s не запущено: %s", notebook_id, exc)


def _default_service_factory() -> NotebookService:
    """Fallback-фабрика: in-memory репозиторий.

    Mongo-реализация регистрируется в ``app.state.notebook_service``
    через ``infrastructure/application/lifecycle.py`` при наличии
    Mongo-инфраструктуры. Этот fallback используется только в
    non-FastAPI контекстах (CLI, scripts, unit-tests).
    """
    return NotebookService(InMemoryNotebookRepository())


@app_state_singleton("notebook_service", factory=_default_service_factory)
def get_notebook_service() -> NotebookService:  # type: ignore[empty-body]
    """Singleton ``NotebookService``. Backend подменяется через app.state."""
