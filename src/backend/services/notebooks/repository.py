"""Protocol ``NotebookRepository`` + in-memory реализация (Wave 9.1).

Бизнес-логика ``NotebookService`` ходит только через Protocol —
конкретный бэкенд (in-memory / MongoDB) подменяется через DI.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from src.backend.services.notebooks.models import Notebook, NotebookVersion

__all__ = ("NotebookRepository", "InMemoryNotebookRepository")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@runtime_checkable
class NotebookRepository(Protocol):
    """Контракт хранилища notebooks (in-memory или Mongo)."""

    async def create(self, notebook: Notebook) -> Notebook: ...

    async def get(self, notebook_id: str) -> Notebook | None: ...

    async def append_version(
        self,
        notebook_id: str,
        content: str,
        changed_by: str,
        summary: str | None = None,
    ) -> Notebook | None: ...

    async def restore_version(
        self, notebook_id: str, version: int, changed_by: str
    ) -> Notebook | None: ...

    async def list_all(
        self,
        *,
        tag: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Notebook]: ...

    async def soft_delete(self, notebook_id: str) -> bool: ...

    async def ensure_indexes(self) -> None: ...


class InMemoryNotebookRepository:
    """In-memory реализация ``NotebookRepository`` для dev/тестов.

    Не для multi-instance deployment — Mongo-реализация в
    ``src/infrastructure/repositories/notebooks_mongo.py``.
    """

    def __init__(self) -> None:
        self._docs: dict[str, Notebook] = {}
        self._lock = asyncio.Lock()

    async def create(self, notebook: Notebook) -> Notebook:
        async with self._lock:
            self._docs[notebook.id] = notebook.model_copy(deep=True)
            return self._docs[notebook.id]

    async def get(self, notebook_id: str) -> Notebook | None:
        async with self._lock:
            doc = self._docs.get(notebook_id)
            return doc.model_copy(deep=True) if doc else None

    async def append_version(
        self,
        notebook_id: str,
        content: str,
        changed_by: str,
        summary: str | None = None,
    ) -> Notebook | None:
        async with self._lock:
            doc = self._docs.get(notebook_id)
            if doc is None or doc.is_deleted:
                return None
            new_version = doc.latest_version + 1
            doc.versions.append(
                NotebookVersion(
                    version=new_version,
                    content=content,
                    changed_by=changed_by,
                    summary=summary,
                )
            )
            doc.latest_version = new_version
            doc.updated_at = _utc_now()
            return doc.model_copy(deep=True)

    async def restore_version(
        self, notebook_id: str, version: int, changed_by: str
    ) -> Notebook | None:
        async with self._lock:
            doc = self._docs.get(notebook_id)
            if doc is None or doc.is_deleted:
                return None
            target = next((v for v in doc.versions if v.version == version), None)
            if target is None:
                return None
            new_version = doc.latest_version + 1
            doc.versions.append(
                NotebookVersion(
                    version=new_version,
                    content=target.content,
                    changed_by=changed_by,
                    summary=f"restore from v{version}",
                )
            )
            doc.latest_version = new_version
            doc.updated_at = _utc_now()
            return doc.model_copy(deep=True)

    async def list_all(
        self,
        *,
        tag: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Notebook]:
        async with self._lock:
            docs = list(self._docs.values())
        if not include_deleted:
            docs = [d for d in docs if not d.is_deleted]
        if tag is not None:
            docs = [d for d in docs if tag in d.tags]
        docs.sort(key=lambda d: d.updated_at, reverse=True)
        return [d.model_copy(deep=True) for d in docs[offset : offset + limit]]

    async def soft_delete(self, notebook_id: str) -> bool:
        async with self._lock:
            doc = self._docs.get(notebook_id)
            if doc is None:
                return False
            doc.is_deleted = True
            doc.updated_at = _utc_now()
            return True

    async def ensure_indexes(self) -> None:
        """In-memory не требует индексов; метод нужен для совместимости."""
        return None
