"""Chat: AI chat endpoint (ai/chat)."""
from __future__ import annotations

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("ChatClient",)


class ChatClient(BaseAPIClient):
    """Клиент для AI chat endpoint."""

    def chat(self, message: str, session_id: str = "default") -> str:
        result = self._request(
            "POST",
            "/api/v1/ai/chat",
            json={"message": message, "session_id": session_id},
        )
        return (
            result.get("response", str(result))
            if isinstance(result, dict)
            else str(result)
        )
