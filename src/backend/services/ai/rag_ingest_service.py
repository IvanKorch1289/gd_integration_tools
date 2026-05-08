"""RagIngestService — orchestration загрузки документов в RAG (К4 MVP, Шаг 8).

Поддерживает 2 режима:

* **inline**: ``RAGService.ingest`` вызывается прямо в текущем event-loop
  (default; нужен когда TaskIQ disabled);
* **deferred**: enqueue в TaskIQ-broker (Sprint 5).

Status-tracking — in-memory dict, ключ task_id → state. Sprint 5 заменит
на Redis HSET / TaskIQ task_meta.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("RagIngestService", "get_rag_ingest_service")


class RagIngestService:
    """Coordinator для multi-file RAG ingest."""

    def __init__(
        self,
        rag_service: Any | None = None,
        deferred: bool = False,
    ) -> None:
        self._rag_service = rag_service
        self._deferred = deferred
        self._tasks: dict[str, dict[str, Any]] = {}

    def _ensure_rag(self) -> Any:
        if self._rag_service is not None:
            return self._rag_service
        from src.backend.core.di.app_state import get_app_ref

        app = get_app_ref()
        rag = getattr(app.state, "rag_service", None) if app is not None else None
        if rag is None:
            raise RuntimeError(
                "RagIngestService: app.state.rag_service не зарегистрирован."
            )
        self._rag_service = rag
        return rag

    async def ingest(
        self,
        files: list[tuple[str, bytes]],
        *,
        collection: str = "default",
    ) -> dict[str, Any]:
        """Запускает ingest. Возвращает task_id + start-метку."""
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = {
            "status": "running",
            "total": len(files),
            "processed": 0,
            "doc_ids": [],
            "errors": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        coroutine = self._run(task_id, files, collection)
        if self._deferred:
            try:
                from src.backend.core.utils.task_registry import get_task_registry

                get_task_registry().create_task(coroutine, name=f"rag-ingest-{task_id}")
            except Exception:  # noqa: BLE001
                asyncio.create_task(coroutine)
        else:
            await coroutine

        return {"task_id": task_id, **self._tasks[task_id]}

    async def _run(
        self,
        task_id: str,
        files: list[tuple[str, bytes]],
        collection: str,
    ) -> None:
        rag = self._ensure_rag()
        state = self._tasks[task_id]
        for filename, content_bytes in files:
            try:
                content_text = content_bytes.decode("utf-8", errors="replace")
                doc_id = await rag.ingest(
                    content_text,
                    metadata={"filename": filename},
                    namespace=collection,
                )
                state["doc_ids"].append(doc_id)
            except Exception as exc:  # noqa: BLE001
                state["errors"].append({"file": filename, "error": str(exc)})
            state["processed"] += 1
        state["status"] = "completed" if not state["errors"] else "completed_with_errors"
        state["finished_at"] = datetime.now(timezone.utc).isoformat()

    def status(self, task_id: str) -> dict[str, Any] | None:
        return self._tasks.get(task_id)


_singleton: RagIngestService | None = None


def get_rag_ingest_service() -> RagIngestService:
    """Возвращает singleton :class:`RagIngestService`."""
    global _singleton
    if _singleton is None:
        _singleton = RagIngestService()
    return _singleton
