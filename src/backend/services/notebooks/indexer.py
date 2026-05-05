"""NotebookIndexer — индексация notebook'ов в RAG (Wave 12).

Каждый ``Notebook`` после ``create`` / ``update_content`` отправляется
в ``RAGService.ingest``. ID документа в RAG = ``notebook.id`` + версия,
так что историю версий можно искать. Индексация — fire-and-forget,
ошибки логируются и не пробрасываются caller'у (поведение совместимо
с ``OrderIndexer.index_one_fire_and_forget``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.backend.core.di import app_state_singleton

if TYPE_CHECKING:
    from src.backend.services.ai.rag_service import RAGService
    from src.backend.services.notebooks.models import Notebook

__all__ = ("NotebookIndexer", "get_notebook_indexer")

logger = logging.getLogger(__name__)

_NAMESPACE = "notebooks"


class NotebookIndexer:
    """Индексирует notebooks в ``RAGService`` (vector store)."""

    def __init__(self, rag_service: RAGService) -> None:
        self._rag = rag_service

    async def index_one(self, notebook: Notebook) -> str | None:
        """Индексирует актуальную версию notebook'а. Возвращает doc_id RAG."""
        content = notebook.current_content
        if not content:
            return None
        try:
            return await self._rag.ingest(
                content=content,
                metadata={
                    "notebook_id": notebook.id,
                    "title": notebook.title,
                    "version": notebook.latest_version,
                    "tags": list(notebook.tags),
                    "created_by": notebook.created_by,
                },
                namespace=_NAMESPACE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "NotebookIndexer.index_one failed (notebook %s): %s", notebook.id, exc
            )
            return None

    async def delete_one(self, notebook_id: str) -> bool:
        """Удаляет chunks notebook'а из RAG (по metadata.notebook_id)."""
        try:
            return await self._rag.delete(notebook_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "NotebookIndexer.delete_one failed (notebook %s): %s", notebook_id, exc
            )
            return False

    async def bulk_reindex(self, notebooks: list[Notebook]) -> int:
        """Полная переиндексация переданного списка. Возвращает успешные."""
        if not notebooks:
            return 0
        ok = 0
        for notebook in notebooks:
            if await self.index_one(notebook) is not None:
                ok += 1
        return ok

    def index_one_fire_and_forget(self, notebook: Notebook) -> None:
        """Не блокирует caller — отправляет index_one через ``create_task``."""
        try:
            asyncio.create_task(self.index_one(notebook))
        except RuntimeError:
            return


def _factory() -> NotebookIndexer:
    from src.backend.services.ai.rag_service import get_rag_service

    return NotebookIndexer(get_rag_service())


@app_state_singleton("notebook_indexer", factory=_factory)
def get_notebook_indexer() -> NotebookIndexer:
    """Singleton ``NotebookIndexer``."""
