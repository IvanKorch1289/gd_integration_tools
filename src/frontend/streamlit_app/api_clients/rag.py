"""RAG API клиент."""

from __future__ import annotations

from typing import Any

import httpx

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient
from src.frontend.streamlit_app.config import API_TIMEOUT_RAG

__all__ = ("RAGClient",)


class RAGClient(BaseAPIClient):
    """Клиент для RAG operations (stats, search, upload, augment)."""

    def get_stats(self, *, collection: str | None = None) -> dict[str, Any]:
        """GET /api/v1/rag/stats — получить статус RAG."""
        params: dict[str, str] = {}
        if collection:
            params["collection"] = collection
        try:
            resp = self.get("/api/v1/rag/stats", params=params)
            return resp if isinstance(resp, dict) else {}
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as stats_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1076: narrow exceptions + observability.
            # ConnectionError/TimeoutError — server unreachable, RuntimeError
            # — API failure, ValueError — invalid response, TypeError —
            # wrong type.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_rag_client.stats_failed",
                extra={"error": str(stats_exc)},
            )
            return {}

    def search(
        self, query: str, top_k: int = 5, *, namespace: str | None = None
    ) -> dict[str, Any]:
        """POST /api/v1/rag/search — семантический поиск."""
        body: dict[str, Any] = {"query": query, "top_k": top_k}
        if namespace:
            body["namespace"] = namespace
        try:
            return self.post("/api/v1/rag/search", json=body)
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as search_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1076: см. выше — mirror для search.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_rag_client.search_failed",
                extra={"error": str(search_exc)},
            )
            return {}

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        namespace: str = "default",
        metadata_json: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/rag/upload — загрузить документ (multipart)."""
        files = {"file": (filename, file_bytes, content_type)}
        data: dict[str, str] = {"namespace": namespace}
        if metadata_json:
            data["metadata_json"] = metadata_json
        try:
            return self._multipart_post("/api/v1/rag/upload", files=files, data=data)
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, OSError) as upload_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1076: см. выше — mirror для upload (добавлен
            # OSError для multipart I/O).
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_rag_client.upload_failed",
                extra={"error": str(upload_exc)},
            )
            return {}

    def augment(
        self, query: str, *, namespace: str | None = None, top_k: int = 5
    ) -> dict[str, Any]:
        """POST /api/v1/rag/augment — augmentation с freshness badge."""
        body: dict[str, Any] = {"query": query, "top_k": top_k}
        if namespace:
            body["namespace"] = namespace
        try:
            return self.post("/api/v1/rag/augment", json=body)
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as augment_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1076: см. выше — mirror для augment.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_rag_client.augment_failed",
                extra={"error": str(augment_exc)},
            )
            return {}

    def _multipart_post(
        self, path: str, files: dict, data: dict[str, str]
    ) -> dict[str, Any]:
        """POST с multipart/form-data (для file uploads)."""
        headers = {k: v for k, v in self._headers().items() if k != "Content-Type"}
        with httpx.Client(timeout=API_TIMEOUT_RAG) as client:
            response = client.request(
                "POST",
                f"{self._base_url}{path}",
                files=files,
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
