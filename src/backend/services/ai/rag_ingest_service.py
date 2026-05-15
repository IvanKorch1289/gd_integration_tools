"""RagIngestService — orchestration загрузки документов в RAG (К4 MVP, Шаг 8).

Поддерживает 2 режима:

* **inline**: ``RAGService.ingest`` вызывается прямо в текущем event-loop
  (default);
* **deferred**: enqueue в Temporal-activity (Sprint 8 K2 W1: TaskIQ удалён).

Wave D.2 / Track D AI: status-tracking вынесен в ``IngestStateStore``
(memory / redis). ``chunker_fingerprint`` пишется в metadata каждого
ingest'а, чтобы reindex-сервис мог обнаружить устаревшие chunks при
смене ``RAG_INGEST_CHUNKER_FINGERPRINT_VERSION``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.backend.services.ai.rag_ingest_store import (
    IngestStateStore,
    InMemoryIngestStateStore,
)

logger = logging.getLogger(__name__)

__all__ = ("RagIngestService", "get_rag_ingest_service")


def _chunker_fingerprint() -> str:
    """Сборка fingerprint текущей chunker-конфигурации.

    Формат: ``v{version}:{size}:{overlap}``. Меняется при bump
    ``RAG_INGEST_CHUNKER_FINGERPRINT_VERSION`` или параметров chunker.
    """
    try:
        from src.backend.core.config.ai_2026 import rag_ingest_settings
        from src.backend.core.config.rag import rag_settings

        version = rag_ingest_settings.chunker_fingerprint_version
        size = rag_settings.chunk_size
        overlap = rag_settings.chunk_overlap
    except Exception:  # noqa: BLE001
        version, size, overlap = 1, 0, 0
    raw = f"v{version}:{size}:{overlap}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class RagIngestService:
    """Coordinator для multi-file RAG ingest."""

    def __init__(
        self,
        rag_service: Any | None = None,
        deferred: bool = False,
        store: IngestStateStore | None = None,
    ) -> None:
        self._rag_service = rag_service
        self._deferred = deferred
        self._store: IngestStateStore = store or InMemoryIngestStateStore()

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
        payload = {
            "task_id": task_id,
            "status": "running",
            "total": len(files),
            "processed": 0,
            "doc_ids": [],
            "errors": [],
            "collection": collection,
            "chunker_fingerprint": _chunker_fingerprint(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._store.create(task_id, payload)

        coroutine = self._run(task_id, files, collection, payload)
        if self._deferred:
            try:
                from src.backend.core.utils.task_registry import get_task_registry

                get_task_registry().create_task(coroutine, name=f"rag-ingest-{task_id}")
            except Exception:  # noqa: BLE001
                asyncio.create_task(coroutine)
        else:
            await coroutine

        snapshot = await self._store.get(task_id)
        return snapshot or payload

    async def _run(
        self,
        task_id: str,
        files: list[tuple[str, bytes]],
        collection: str,
        state: dict[str, Any],
    ) -> None:
        rag = self._ensure_rag()
        fingerprint = state["chunker_fingerprint"]
        for filename, content_bytes in files:
            try:
                content_text = content_bytes.decode("utf-8", errors="replace")
                doc_id = await rag.ingest(
                    content_text,
                    metadata={
                        "filename": filename,
                        "chunker_fingerprint": fingerprint,
                    },
                    namespace=collection,
                )
                state["doc_ids"].append(doc_id)
            except Exception as exc:  # noqa: BLE001
                state["errors"].append({"file": filename, "error": str(exc)})
            state["processed"] += 1
            await self._store.update(
                task_id,
                processed=state["processed"],
                doc_ids=list(state["doc_ids"]),
                errors=list(state["errors"]),
            )
        state["status"] = (
            "completed" if not state["errors"] else "completed_with_errors"
        )
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        await self._store.update(
            task_id, status=state["status"], finished_at=state["finished_at"]
        )

    async def status(self, task_id: str) -> dict[str, Any] | None:
        """Async-снимок состояния задачи (D.2)."""
        return await self._store.get(task_id)

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Последние ``limit`` задач (D.2)."""
        return await self._store.list_recent(limit=limit)


_singleton: RagIngestService | None = None


def get_rag_ingest_service() -> RagIngestService:
    """Возвращает singleton :class:`RagIngestService`.

    Стартовый backend выбирается по ``rag_ingest_settings.state_backend``
    (default ``memory`` — backward-compat).
    """
    global _singleton
    if _singleton is None:
        try:
            from src.backend.core.config.ai_2026 import rag_ingest_settings
            from src.backend.services.ai.rag_ingest_store import (
                build_ingest_state_store,
            )

            store = build_ingest_state_store(rag_ingest_settings.state_backend)
            _singleton = RagIngestService(
                deferred=rag_ingest_settings.deferred, store=store
            )
        except Exception:  # noqa: BLE001
            _singleton = RagIngestService()
    return _singleton
