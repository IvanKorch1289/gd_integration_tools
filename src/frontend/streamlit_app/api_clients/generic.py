"""HTTP-клиент для вызова FastAPI backend из Streamlit.

Sprint 45 W1 (TD-011 closure): APIClient — back-compat facade,
делегирует 46 domain methods в 12 специализированных domain classes:

- :class:`MetricsClient`    — get_metrics, get_health
- :class:`TenantsClient`    — get_tenants, get_tenant_detail
- :class:`OrdersClient`     — get/create/update/delete_order
- :class:`ChatClient`       — chat
- :class:`FlagsClient`      — get_flags, toggle_flag, list/set/clear_overrides
- :class:`ConfigClient`     — get_config, get_trace_logs
- :class:`WorkflowsClient`  — list_workflows, get/retry/cancel/resume/trigger
- :class:`DSLRoutesClient`  — list/get/create/update/delete/validate/diff dsl_route
- :class:`FeedbackClient`   — list/label/index feedback
- :class:`InventoryClient`  — plugins_inventory, routes_inventory
- :class:`CapabilityClient` — capability/processor catalogs, audit, graphs, scaffold
- :class:`LogsClient`       — list_step_logs, get_step_detail

Все domain classes extend :class:`BaseAPIClient` (retry + JWT + 401/5xx).
APIClient наследует :class:`BaseAPIClient` (HTTP transport) и
содержит 46 thin wrapper-методов для back-compat (hasattr + вызов
domain client). 44+ pages работают без изменений.
"""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient
from src.frontend.streamlit_app.api_clients.capability import CapabilityClient
from src.frontend.streamlit_app.api_clients.chat import ChatClient
from src.frontend.streamlit_app.api_clients.config import ConfigClient
from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient
from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient
from src.frontend.streamlit_app.api_clients.flags import FlagsClient
from src.frontend.streamlit_app.api_clients.inventory import InventoryClient
from src.frontend.streamlit_app.api_clients.logs import LogsClient
from src.frontend.streamlit_app.api_clients.metrics import MetricsClient
from src.frontend.streamlit_app.api_clients.orders import OrdersClient
from src.frontend.streamlit_app.api_clients.tenants import TenantsClient
from src.frontend.streamlit_app.api_clients.workflows import WorkflowsClient
from src.frontend.streamlit_app.config import get_api_base_url

__all__ = ("APIClient", "get_api_client")

_BASE_URL = get_api_base_url()


class APIClient(BaseAPIClient):
    """Back-compat facade: 46 thin wrapper methods → 12 domain clients.

    Inherits from :class:`BaseAPIClient`:
    - ``__init__(base_url, token=None, max_retries=3, timeout=15.0)``
    - ``get/post/put/patch/delete`` (HTTP)
    - ``set_token`` (JWT propagation)
    - 401 → PermissionError, 5xx → HTTPStatusError

    Back-compat: все 46 domain methods (``client.get_metrics()`` etc.)
    работают через thin wrapper → domain client. 44+ pages без изменений.
    """

    def __init__(self, base_url: str = _BASE_URL) -> None:
        super().__init__(base_url=base_url)
        # Instantiate 12 domain clients (один на домен).
        self._metrics = MetricsClient(base_url=base_url)
        self._tenants = TenantsClient(base_url=base_url)
        self._orders = OrdersClient(base_url=base_url)
        self._chat = ChatClient(base_url=base_url)
        self._flags = FlagsClient(base_url=base_url)
        self._config = ConfigClient(base_url=base_url)
        self._workflows = WorkflowsClient(base_url=base_url)
        self._dsl_routes = DSLRoutesClient(base_url=base_url)
        self._feedback = FeedbackClient(base_url=base_url)
        self._inventory = InventoryClient(base_url=base_url)
        self._capability = CapabilityClient(base_url=base_url)
        self._logs = LogsClient(base_url=base_url)

    # ── Metrics (2) ────────────────────────────────────────────────
    def get_metrics(self) -> dict[str, Any]:
        return self._metrics.get_metrics()

    def get_health(self) -> dict[str, Any]:
        return self._metrics.get_health()

    # ── Tenants (2) ────────────────────────────────────────────────
    def get_tenants(self) -> dict[str, Any]:
        return self._tenants.get_tenants()

    def get_tenant_detail(self, tenant_id: str) -> dict[str, Any]:
        return self._tenants.get_tenant_detail(tenant_id)

    # ── Orders (4) ─────────────────────────────────────────────────
    def get_orders(self, page: int = 1, size: int = 50) -> Any:
        return self._orders.get_orders(page=page, size=size)

    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._orders.create_order(data)

    def update_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return self._orders.update_order(order_id, data)

    def delete_order(self, order_id: int) -> None:
        return self._orders.delete_order(order_id)

    # ── Chat (1) ───────────────────────────────────────────────────
    def chat(self, message: str, session_id: str = "default") -> str:
        return self._chat.chat(message, session_id)

    # ── Flags (5) ──────────────────────────────────────────────────
    def get_flags(self) -> list[dict[str, Any]]:
        return self._flags.get_flags()

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        return self._flags.toggle_flag(name, enabled)

    def list_overrides(self) -> dict[str, Any]:
        return self._flags.list_overrides()

    def set_override(
        self, flag: str, value: Any, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        return self._flags.set_override(flag, value, tenant_id, actor)

    def clear_override(
        self, flag: str, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        return self._flags.clear_override(flag, tenant_id, actor)

    # ── Config (2) ─────────────────────────────────────────────────
    def get_config(self) -> dict[str, Any]:
        return self._config.get_config()

    def get_trace_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._config.get_trace_logs(limit)

    # ── Workflows (7) ──────────────────────────────────────────────
    def list_workflows(
        self,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return self._workflows.list_workflows(**kwargs)

    def get_workflow(self, instance_id: str) -> dict[str, Any] | None:
        return self._workflows.get_workflow(instance_id)

    def get_workflow_events(
        self, instance_id: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return self._workflows.get_workflow_events(instance_id, **kwargs)

    def retry_workflow(self, instance_id: str) -> bool:
        return self._workflows.retry_workflow(instance_id)

    def cancel_workflow(self, instance_id: str, **kwargs: Any) -> bool:
        return self._workflows.cancel_workflow(instance_id, **kwargs)

    def resume_workflow(self, instance_id: str) -> bool:
        return self._workflows.resume_workflow(instance_id)

    def trigger_workflow(
        self, workflow_name: str, payload: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        return self._workflows.trigger_workflow(workflow_name, payload, **kwargs)

    # ── DSL Routes (8) ─────────────────────────────────────────────
    def get_routes(self) -> list[dict[str, Any]]:
        return self._dsl_routes.get_routes()

    def list_dsl_routes(self) -> list[str]:
        return self._dsl_routes.list_dsl_routes()

    def get_dsl_route(self, route_id: str) -> dict[str, Any] | None:
        return self._dsl_routes.get_dsl_route(route_id)

    def create_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        return self._dsl_routes.create_dsl_route(yaml_str)

    def update_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any]:
        return self._dsl_routes.update_dsl_route(route_id, yaml_str)

    def delete_dsl_route(self, route_id: str) -> bool:
        return self._dsl_routes.delete_dsl_route(route_id)

    def validate_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        return self._dsl_routes.validate_dsl_route(yaml_str)

    def diff_dsl_route(
        self, route_id: str, yaml_str: str
    ) -> dict[str, Any] | None:
        return self._dsl_routes.diff_dsl_route(route_id, yaml_str)

    # ── Feedback (5) ───────────────────────────────────────────────
    def list_feedback_pending(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        return self._feedback.list_feedback_pending(**kwargs)

    def list_feedback_labeled(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        return self._feedback.list_feedback_labeled(**kwargs)

    def get_feedback_stats(self) -> dict[str, int]:
        return self._feedback.get_feedback_stats()

    def label_feedback(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._feedback.label_feedback(*args, **kwargs)

    def index_feedback_to_rag(self, *args: Any, **kwargs: Any) -> dict[str, int]:
        return self._feedback.index_feedback_to_rag(*args, **kwargs)

    # ── Inventory (2) ──────────────────────────────────────────────
    def get_plugins_inventory(self) -> dict[str, Any]:
        return self._inventory.get_plugins_inventory()

    def get_routes_inventory(self) -> dict[str, Any]:
        return self._inventory.get_routes_inventory()

    # ── Capability (6) ─────────────────────────────────────────────
    def get_capability_catalog(self) -> dict[str, Any]:
        return self._capability.get_capability_catalog()

    def get_processor_catalog(
        self, query: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        return self._capability.get_processor_catalog(query, **kwargs)

    def get_audit_events(
        self, plugin: str | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return self._capability.get_audit_events(plugin, **kwargs)

    def get_dependency_graph(self) -> dict[str, Any]:
        return self._capability.get_dependency_graph()

    def get_capability_graph(self) -> dict[str, Any]:
        return self._capability.get_capability_graph()

    def scaffold_plugin(self, name: str, **kwargs: Any) -> dict[str, Any]:
        return self._capability.scaffold_plugin(name, **kwargs)

    # ── Logs (2) ───────────────────────────────────────────────────
    def list_step_logs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._logs.list_step_logs(**kwargs)

    def get_step_detail(self, workflow_id: str) -> dict[str, Any]:
        return self._logs.get_step_detail(workflow_id)


def get_api_client() -> APIClient:
    return APIClient()
