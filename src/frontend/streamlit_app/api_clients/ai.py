"""AI/RAG/LiteLLM API клиент."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("AIClient",)


class AIClient(BaseAPIClient):
    """Клиент для AI/RAG/LiteLLM operations."""

    def chat(self, message: str, session_id: str = "default") -> str:
        """POST /api/v1/ai/chat — отправить сообщение в AI-чат."""
        result = self.post(
            "/api/v1/ai/chat",
            json={"message": message, "session_id": session_id},
        )
        return (
            result.get("response", str(result))
            if isinstance(result, dict)
            else str(result)
        )

    def list_feedback_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """GET /api/v1/ai/feedback/pending."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if agent_id:
            params["agent_id"] = agent_id
        return self.get("/api/v1/ai/feedback/pending", params=params)

    def list_feedback_labeled(
        self,
        *,
        label: str | None = None,
        agent_id: str | None = None,
        indexed_in_rag: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /api/v1/ai/feedback/labeled."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if label:
            params["label"] = label
        if agent_id:
            params["agent_id"] = agent_id
        if indexed_in_rag is not None:
            params["indexed_in_rag"] = str(indexed_in_rag).lower()
        return self.get("/api/v1/ai/feedback/labeled", params=params)

    def get_feedback_stats(self) -> dict[str, int]:
        """GET /api/v1/ai/feedback/stats."""
        return self.get("/api/v1/ai/feedback/stats")

    def label_feedback(
        self,
        doc_id: str,
        *,
        label: str,
        comment: str | None = None,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/ai/feedback/{id}/label."""
        payload: dict[str, Any] = {"label": label}
        if comment:
            payload["comment"] = comment
        if operator_id:
            payload["operator_id"] = operator_id
        return self.post(f"/api/v1/ai/feedback/{doc_id}/label", json=payload)

    def index_feedback_to_rag(
        self, *, agent_id: str | None = None, limit: int = 100
    ) -> dict[str, int]:
        """POST /api/v1/ai/feedback/index-to-rag."""
        payload: dict[str, Any] = {"limit": limit}
        if agent_id:
            payload["agent_id"] = agent_id
        return self.post("/api/v1/ai/feedback/index-to-rag", json=payload)
