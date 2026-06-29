"""K4APIClient — расширение :class:`APIClient` для AI Stack 2026 страниц.

Добавляет методы:

* RAG-кэш: ``get_rag_cache_stats``, ``flush_rag_cache_tier``,
  ``get_rag_invalidation_events``;
* RAG-ingest: ``rag_ingest_start``, ``rag_ingest_status``;
* LiteLLM Gateway / Embedding Registry stubs.

Все методы graceful: при недоступном backend'е возвращают пустой словарь
или список — Streamlit-страница рендерит empty-state. Backend failures
логируются на уровне WARNING (видны в production без DEBUG).

Sprint 47 W4: log level повышен с DEBUG до WARNING — backend failures
должны быть visible by default, не только при DEBUG mode. Также fix
``getattr(f, "name", "file")`` edge case для file-like объектов без
``name`` атрибута (используем index-based fallback ``file_{i}``).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.frontend_facade import (  # noqa: E402, F401

from src.backend.core.frontend_facade import get_logger  # noqa: E402, F401
from src.frontend.streamlit_app.api_clients.generic import APIClient

logger = get_logger(__name__)

__all__ = ("K4APIClient",)


class K4APIClient(APIClient):
    """API-клиент с поддержкой страниц 74_Cache_Dashboard / 75_RAG_Ingest_Wizard."""

    def get_rag_cache_stats(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/rag-cache/stats")
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_rag_cache_stats failed: %s", exc)
            return {}

    def flush_rag_cache_tier(self, tier: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"tier": tier} if tier else {}
        try:
            return self._request("POST", "/api/v1/admin/rag-cache/flush", params=params)
        except Exception as exc:  # noqa: BLE001
            logger.warning("flush_rag_cache_tier(tier=%r) failed: %s", tier, exc)
            return {}

    def get_rag_invalidation_events(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self._request(
                "GET", "/api/v1/admin/rag-cache/events", params={"limit": limit}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_rag_invalidation_events(limit=%d) failed: %s", limit, exc
            )
            return []

    def litellm_gateway_stats(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/litellm-gateway/stats")
        except Exception as exc:  # noqa: BLE001
            logger.warning("litellm_gateway_stats failed: %s", exc)
            return {}

    def list_embedding_providers(self) -> list[str]:
        try:
            payload = self._request("GET", "/api/v1/admin/embedding-providers")
            if isinstance(payload, list):
                return [str(x) for x in payload]
            if isinstance(payload, dict):
                return [str(x) for x in payload.get("providers", [])]
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_embedding_providers failed: %s", exc)
            return []

    def rag_ingest_start(
        self, *, files: list[Any], collection: str = "default"
    ) -> dict[str, Any]:
        try:
            # Index-based fallback для file-like объектов без .name
            # (например, BytesIO wrapper, raw bytes). Sprint 47 W4 fix.
            file_payload: list[tuple[str, tuple[str, bytes]]] = []
            for i, f in enumerate(files):
                name = getattr(f, "name", None) or f"file_{i}"
                file_payload.append(("files", (name, f.read())))
            return self._request(
                "POST",
                "/api/v1/rag/ingest/start",
                files=file_payload,
                data={"collection": collection},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rag_ingest_start(collection=%r) failed: %s", collection, exc
            )
            return {"task_id": None, "error": str(exc)}

    def rag_ingest_status(self, task_id: str) -> dict[str, Any]:
        try:
            return self._request("GET", f"/api/v1/rag/ingest/status/{task_id}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("rag_ingest_status(task_id=%r) failed: %s", task_id, exc)
            return {}

    def rag_search_preview(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        try:
            return self._request(
                "GET", "/api/v1/rag/search", params={"query": query, "top_k": top_k}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("rag_search_preview(query=%r) failed: %s", query, exc)
            return []

    def bulk_rag_ingest(
        self, *, documents: list[dict[str, Any]], collection: str = "default"
    ) -> dict[str, Any]:
        """Bulk ingest documents via POST /api/v1/rag/bulk-ingest (S19 K4 W1).

        Args:
            documents: List of {"content": str, "metadata": dict} objects.
            collection: RAG namespace/collection name.

        Returns:
            dict with task_id, status, doc_ids, errors, etc.
        """
        try:
            return self._request(
                "POST",
                "/api/v1/rag/bulk-ingest",
                json={"documents": documents, "collection": collection},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bulk_rag_ingest(collection=%r, %d docs) failed: %s",
                collection,
                len(documents),
                exc,
            )
            return {"task_id": None, "error": str(exc)}
