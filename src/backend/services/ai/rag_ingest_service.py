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

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger
from src.backend.services.ai.rag_ingest_store import (
    IngestStateStore,
    InMemoryIngestStateStore,
)

logger = get_logger(__name__)

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
    except Exception as _:
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
        self, files: list[tuple[str, bytes]], *, collection: str = "default"
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
            "started_at": datetime.now(UTC).isoformat(),
        }
        await self._store.create(task_id, payload)

        coroutine = self._run(task_id, files, collection, payload)
        if self._deferred:
            from src.backend.core.utils.task_registry import get_task_registry

            get_task_registry().create_task(coroutine, name=f"rag-ingest-{task_id}")
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
        embedding_meta = _resolve_embedding_provenance()
        for filename, content_bytes in files:
            try:
                content_text = content_bytes.decode("utf-8", errors="replace")
                content_text, pii_meta = _maybe_mask_pii(content_text)
                metadata: dict[str, Any] = {
                    "filename": filename,
                    "chunker_fingerprint": fingerprint,
                    **embedding_meta,
                    **pii_meta,
                }
                doc_id = await rag.ingest(
                    content_text, metadata=metadata, namespace=collection
                )
                state["doc_ids"].append(doc_id)
            except Exception as exc:
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
        state["finished_at"] = datetime.now(UTC).isoformat()
        await self._store.update(
            task_id, status=state["status"], finished_at=state["finished_at"]
        )

    async def status(self, task_id: str) -> dict[str, Any] | None:
        """Async-снимок состояния задачи (D.2)."""
        return await self._store.get(task_id)

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Последние ``limit`` задач (D.2)."""
        return await self._store.list_recent(limit=limit)


def _resolve_embedding_provenance() -> dict[str, Any]:
    """Block 3.5 (gap-ai-3.5, ADR-0074): embedding provenance в chunk.metadata.

    Возвращает словарь:
        * ``embedding_provider`` — имя backend ('bge', 'openai', 'gemini', ...);
        * ``embedding_model`` — конкретная модель (например 'BAAI/bge-m3');
        * ``chunker_fingerprint_version`` — int, для detect re-embed/index.

    Retrieval-side проверяет соответствие текущим settings и при mismatch
    либо отбрасывает chunk (strict mode), либо логирует warn + counter
    `rag_model_mismatch_total{chunk_model, current_model}`.

    Graceful: при недоступности rag_settings — возвращает ``{}``,
    не блокирует ingest (existing chunks остаются без provenance).
    """
    try:
        from src.backend.core.config.ai_2026 import rag_ingest_settings
        from src.backend.core.config.rag import rag_settings
    except Exception as _:
        return {}
    return {
        "embedding_provider": getattr(rag_settings, "embedding_provider", "unknown"),
        "embedding_model": getattr(rag_settings, "embedding_model", "unknown"),
        "chunker_fingerprint_version": int(
            getattr(rag_ingest_settings, "chunker_fingerprint_version", 1)
        ),
    }


def _maybe_mask_pii(content_text: str) -> tuple[str, dict[str, Any]]:
    """Block 1.3 (gap-ai-1.3, ADR-0072): one-way PII-anonymize до записи в RAG.

    При ``rag_ingest_settings.pii_mask_on_ingest=True`` пропускает текст
    через DI-resolved sanitizer (Presidio при FEATURE_PRESIDIO_PII_ENABLED,
    иначе legacy regex). В metadata добавляет ``pii_masked: bool`` +
    ``pii_masker_version: str`` для retrieval-side проверки совместимости
    при смене sanitizer.

    Replacements mapping НЕ сохраняется в Qdrant — это one-way операция,
    restore в retrieval не предполагается (для reversible-сценариев см.
    ADR-0068 PIITokenizer).

    Args:
        content_text: Текст документа до ingest.

    Returns:
        Кортеж (masked_text, pii_metadata_dict). При выключенном флаге —
        ``(content_text, {"pii_masked": False})``.
    """
    try:
        from src.backend.core.config.ai_2026 import rag_ingest_settings
    except Exception as _:
        return content_text, {"pii_masked": False}
    if not rag_ingest_settings.pii_mask_on_ingest:
        return content_text, {"pii_masked": False}

    try:
        from src.backend.core.di.providers import get_ai_sanitizer_provider

        sanitizer = get_ai_sanitizer_provider()
        result = sanitizer.sanitize_text(content_text)
        masker_version = type(sanitizer).__name__
        return result.sanitized_text, {
            "pii_masked": True,
            "pii_masker_version": masker_version,
        }
    except Exception as exc:
        logger.warning("rag_ingest_pii_mask_failed: %s", exc)
        return content_text, {"pii_masked": False, "pii_mask_error": str(exc)}


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
        except Exception as _:
            _singleton = RagIngestService()
    return _singleton
