"""Domain-specific API клиенты.

Каждый клиент отвечает за свою предметную область и использует BaseAPIClient.

Sprint 43 W4: добавлены re-exports из generic.py (APIClient, get_api_client)
и k4.py (K4APIClient, get_k4_api_client) для backward-compatibility со
старыми `from src.frontend.streamlit_app.api_client import get_api_client`
imports в pages.
"""

from __future__ import annotations

from src.frontend.streamlit_app.api_clients.admin import AdminClient
from src.frontend.streamlit_app.api_clients.ai import AIClient
from src.frontend.streamlit_app.api_clients.base import BaseAPIClient, get_base_client
from src.frontend.streamlit_app.api_clients.generic import APIClient, get_api_client
from src.frontend.streamlit_app.api_clients.k4 import K4APIClient
from src.frontend.streamlit_app.api_clients.rag import RAGClient
from src.frontend.streamlit_app.api_clients.route import RouteClient
from src.frontend.streamlit_app.api_clients.workflow import WorkflowClient

__all__ = (
    "BaseAPIClient",
    "get_base_client",
    "APIClient",
    "get_api_client",
    "K4APIClient",
    "AdminClient",
    "AIClient",
    "RAGClient",
    "RouteClient",
    "WorkflowClient",
)
