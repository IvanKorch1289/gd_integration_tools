"""K4APIClient — расширение :class:`APIClient` для AI Stack 2026 страниц.

Добавляет методы:

* RAG-кэш: ``get_rag_cache_stats``, ``flush_rag_cache_tier``,
  ``get_rag_invalidation_events``;
* RAG-ingest: ``rag_ingest_start``, ``rag_ingest_status``;
* LiteLLM Gateway / Embedding Registry stubs.

Все методы graceful: при недоступном backend'е возвращают пустой словарь
или список — Streamlit-страница рендерит empty-state.
"""

from __future__ import annotations

import logging
from typing import Any

from src.frontend.streamlit_app.api_client import APIClient

logger = logging.getLogger(__name__)

__all__ = ("K4APIClient",)


class K4APIClient(APIClient):
    """API-клиент с поддержкой страниц 74_Cache_Dashboard / 75_RAG_Ingest_Wizard."""

    def get_rag_cache_stats(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/rag-cache/stats")
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_rag_cache_stats failed: %s", exc)
            return {}

    def flush_rag_cache_tier(self, tier: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"tier": tier} if tier else {}
        try:
            return self._request(
                "POST", "/api/v1/admin/rag-cache/flush", params=params
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("flush_rag_cache_tier failed: %s", exc)
            return {}

    def get_rag_invalidation_events(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self._request(
                "GET",
                "/api/v1/admin/rag-cache/events",
                params={"limit": limit},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_rag_invalidation_events failed: %s", exc)
            return []

    def litellm_gateway_stats(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/litellm-gateway/stats")
        except Exception as exc:  # noqa: BLE001
            logger.debug("litellm_gateway_stats failed: %s", exc)
            return {}

    def list_embedding_providers(self) -> list[str]:
        try:
            payload = self._request(
                "GET", "/api/v1/admin/embedding-providers"
            )
            if isinstance(payload, list):
                return [str(x) for x in payload]
            if isinstance(payload, dict):
                return [str(x) for x in payload.get("providers", [])]
            return []
        except Exception as exc:  # noqa: BLE001
            logger.debug("list_embedding_providers failed: %s", exc)
            return []

    def rag_ingest_start(
        self, *, files: list[Any], collection: str = "default"
    ) -> dict[str, Any]:
        try:
            file_payload = [("files", (getattr(f, "name", "file"), f.read())) for f in files]
            return self._request(
                "POST",
                "/api/v1/rag/ingest/start",
                files=file_payload,
                data={"collection": collection},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("rag_ingest_start failed: %s", exc)
            return {"task_id": None, "error": str(exc)}

    def rag_ingest_status(self, task_id: str) -> dict[str, Any]:
        try:
            return self._request(
                "GET", f"/api/v1/rag/ingest/status/{task_id}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("rag_ingest_status failed: %s", exc)
            return {}

    def rag_search_preview(
        self, query: str, top_k: int = 5
    ) -> list[dict[str, Any]]:
        try:
            return self._request(
                "GET",
                "/api/v1/rag/search",
                params={"query": query, "top_k": top_k},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("rag_search_preview failed: %s", exc)
            return []
