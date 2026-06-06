"""Domain-specific API клиенты.

Sprint 45 W1 (TD-011 closure): APIClient split на 12 specialized domain
classes. APIClient (generic.py) — thin facade с __getattr__ делегированием.

Hierarchy:
- BaseAPIClient (base.py) — retry + JWT + 401/5xx, HTTP transport
- 12 domain clients — каждый отвечает за свой домен
- APIClient (generic.py) — back-compat facade для 44+ pages

Re-exports ниже для удобства (`from .api_clients import MetricsClient`).
"""

from __future__ import annotations

from src.frontend.streamlit_app.api_clients.admin import AdminClient
from src.frontend.streamlit_app.api_clients.base import BaseAPIClient, get_base_client
from src.frontend.streamlit_app.api_clients.capability import CapabilityClient
from src.frontend.streamlit_app.api_clients.chat import ChatClient
from src.frontend.streamlit_app.api_clients.config import ConfigClient
from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient
from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient
from src.frontend.streamlit_app.api_clients.flags import FlagsClient
from src.frontend.streamlit_app.api_clients.generic import APIClient, get_api_client
from src.frontend.streamlit_app.api_clients.inventory import InventoryClient
from src.frontend.streamlit_app.api_clients.k4 import K4APIClient
from src.frontend.streamlit_app.api_clients.logs import LogsClient
from src.frontend.streamlit_app.api_clients.metrics import MetricsClient
from src.frontend.streamlit_app.api_clients.orders import OrdersClient
from src.frontend.streamlit_app.api_clients.rag import RAGClient
from src.frontend.streamlit_app.api_clients.tenants import TenantsClient
from src.frontend.streamlit_app.api_clients.workflows import WorkflowsClient

__all__ = (
    "BaseAPIClient",
    "get_base_client",
    "APIClient",
    "get_api_client",
    "K4APIClient",
    "AdminClient",
    "RAGClient",
    "MetricsClient",
    "TenantsClient",
    "OrdersClient",
    "ChatClient",
    "FlagsClient",
    "ConfigClient",
    "WorkflowsClient",
    "DSLRoutesClient",
    "FeedbackClient",
    "InventoryClient",
    "CapabilityClient",
    "LogsClient",
)
