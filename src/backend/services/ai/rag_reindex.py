"""RagReindexService — detection устаревших chunks (D.2 / Track D AI).

MVP-вариант: только обнаружение. Полный re-embed больших коллекций
out-of-scope D.2 (часовой объём работ). Сервис сканирует vector store
по namespace и собирает chunks с ``chunker_fingerprint``, отличным от
текущего (или с отсутствующим fingerprint — legacy ingests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("RagReindexService", "ReindexReport", "get_rag_reindex_service")


@dataclass(slots=True)
class ReindexReport:
    """Отчёт о найденных устаревших chunks в namespace."""

    namespace: str
    current_fingerprint: str
    total_scanned: int = 0
    stale: int = 0
    stale_doc_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "current_fingerprint": self.current_fingerprint,
            "total_scanned": self.total_scanned,
            "stale": self.stale,
            "stale_doc_ids": self.stale_doc_ids,
        }


class RagReindexService:
    """Сервис detection устаревших chunks по chunker_fingerprint."""

    def __init__(self, rag_service: Any | None = None) -> None:
        self._rag_service = rag_service

    def _ensure_rag(self) -> Any:
        if self._rag_service is not None:
            return self._rag_service
        from src.backend.core.di.app_state import get_app_ref

        app = get_app_ref()
        rag = getattr(app.state, "rag_service", None) if app is not None else None
        if rag is None:
            raise RuntimeError(
                "RagReindexService: app.state.rag_service не зарегистрирован."
            )
        self._rag_service = rag
        return rag

    async def reindex_namespace(
        self,
        namespace: str,
        *,
        since_chunker_hash: str | None = None,
        limit: int = 1000,
    ) -> ReindexReport:
        """Сканирует ``namespace`` и собирает устаревшие chunks.

        Args:
            namespace: логическая партиция RAG-коллекции.
            since_chunker_hash: ожидаемый актуальный fingerprint;
                если ``None`` — берётся текущий из ``ai_stack`` config.
            limit: максимум chunks для сканирования.
        """
        from src.backend.services.ai.rag_ingest_service import _chunker_fingerprint

        current = since_chunker_hash or _chunker_fingerprint()
        report = ReindexReport(namespace=namespace, current_fingerprint=current)

        rag = self._ensure_rag()
        store = getattr(rag, "_store", None)
        if store is None or not hasattr(store, "scroll_where"):
            logger.info(
                "RagReindexService: backend %s не поддерживает scroll_where — "
                "detection пропущен",
                type(store).__name__ if store is not None else "None",
            )
            return report

        try:
            rows = await store.scroll_where({"namespace": namespace}, limit=limit)
        except Exception as exc:
            logger.warning("scroll_where(%s) failed: %s", namespace, exc)
            return report

        seen_doc_ids: set[str] = set()
        for row in rows:
            report.total_scanned += 1
            meta = row.get("metadata") if isinstance(row, dict) else None
            if not isinstance(meta, dict):
                continue
            fp = meta.get("chunker_fingerprint")
            if fp == current:
                continue
            doc_id = meta.get("doc_id")
            if not doc_id or doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(str(doc_id))
            report.stale += 1
            report.stale_doc_ids.append(str(doc_id))

        return report


_singleton: RagReindexService | None = None


def get_rag_reindex_service() -> RagReindexService:
    """Возвращает singleton :class:`RagReindexService`."""
    global _singleton
    if _singleton is None:
        _singleton = RagReindexService()
    return _singleton
