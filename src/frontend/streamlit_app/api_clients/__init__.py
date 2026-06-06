"""Domain-specific API клиенты.

Каждый клиент отвечает за свою предметную область и использует BaseAPIClient.

Sprint 44 W7 (TD-010): удалены 9 unused domain clients (ai, api_caller,
cron, route, workflow, workflow_version, action_bus_client,
plugin_marketplace_client, schema_registry_client) — total 1047 LOC dead code.
Все они imported by 0 pages и 0 tests.

Re-exports kept:
- ``APIClient`` / ``get_api_client`` (generic.py, 47+ domain methods)
- ``K4APIClient`` (k4.py, AI Stack 2026 extension)
- ``AdminClient`` (admin.py, used by 51_Healthcheck.py)
- ``RAGClient`` (rag.py, used by 22_RAG_Console.py)
- ``BaseAPIClient`` / ``get_base_client`` (base.py, source of truth)
"""

from __future__ import annotations

from src.frontend.streamlit_app.api_clients.admin import AdminClient
from src.frontend.streamlit_app.api_clients.base import BaseAPIClient, get_base_client
from src.frontend.streamlit_app.api_clients.generic import APIClient, get_api_client
from src.frontend.streamlit_app.api_clients.k4 import K4APIClient
from src.frontend.streamlit_app.api_clients.rag import RAGClient

__all__ = (
    "BaseAPIClient",
    "get_base_client",
    "APIClient",
    "get_api_client",
    "K4APIClient",
    "AdminClient",
    "RAGClient",
)
