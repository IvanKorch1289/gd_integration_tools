"""Domain-specific API клиенты.

Каждый клиент отвечает за свою предметную область и использует BaseAPIClient.
"""

from __future__ import annotations

from src.frontend.streamlit_app.api_clients.admin import AdminClient
from src.frontend.streamlit_app.api_clients.ai import AIClient
from src.frontend.streamlit_app.api_clients.base import BaseAPIClient, get_base_client
from src.frontend.streamlit_app.api_clients.rag import RAGClient
from src.frontend.streamlit_app.api_clients.route import RouteClient
from src.frontend.streamlit_app.api_clients.workflow import WorkflowClient

__all__ = (
    "BaseAPIClient",
    "get_base_client",
    "AdminClient",
    "AIClient",
    "RAGClient",
    "RouteClient",
    "WorkflowClient",
)
