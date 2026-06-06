"""Coverage tests для APIClient (generic.py) back-compat facade.

Sprint 47 W2: test all 46 thin wrapper methods → 12 domain clients.

APIClient (S45 W1) — back-compat facade с 46 wrapper методами,
делегирующими в 12 domain clients. Эти тесты verify что delegation
работает корректно и wrappers передают args/kwargs правильно.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.frontend.streamlit_app.api_clients.generic import APIClient

# (wrapper_name, domain_attr, domain_method_name, args, kwargs)
# Заполняем каждый wrapper с realistic args.
WRAPPER_MAPPING: list[tuple[str, str, str, tuple, dict[str, Any]]] = [
    # Metrics (2)
    ("get_metrics", "_metrics", "get_metrics", (), {}),
    ("get_health", "_metrics", "get_health", (), {}),
    # Tenants (2)
    ("get_tenants", "_tenants", "get_tenants", (), {}),
    ("get_tenant_detail", "_tenants", "get_tenant_detail", ("t1",), {}),
    # Orders (4)
    ("get_orders", "_orders", "get_orders", (), {"page": 1, "size": 50}),
    ("create_order", "_orders", "create_order", ({"name": "x"},), {}),
    ("update_order", "_orders", "update_order", (1, {"name": "y"}), {}),
    ("delete_order", "_orders", "delete_order", (42,), {}),
    # Chat (1)
    ("chat", "_chat", "chat", ("hello",), {"session_id": "s1"}),
    # Flags (5)
    ("get_flags", "_flags", "get_flags", (), {}),
    ("toggle_flag", "_flags", "toggle_flag", ("flag_x", True), {}),
    ("list_overrides", "_flags", "list_overrides", (), {}),
    ("set_override", "_flags", "set_override", ("f", "v"), {"tenant_id": "t1", "actor": "a1"}),
    ("clear_override", "_flags", "clear_override", ("f",), {"tenant_id": "t1"}),
    # Config (2)
    ("get_config", "_config", "get_config", (), {}),
    ("get_trace_logs", "_config", "get_trace_logs", (), {"limit": 50}),
    # Workflows (7)
    ("list_workflows", "_workflows", "list_workflows", (), {"limit": 10}),
    ("get_workflow", "_workflows", "get_workflow", ("wf-1",), {}),
    ("get_workflow_events", "_workflows", "get_workflow_events", ("wf-1",), {"limit": 100}),
    ("retry_workflow", "_workflows", "retry_workflow", ("wf-1",), {}),
    ("cancel_workflow", "_workflows", "cancel_workflow", ("wf-1",), {"reason": "user"}),
    ("resume_workflow", "_workflows", "resume_workflow", ("wf-1",), {}),
    ("trigger_workflow", "_workflows", "trigger_workflow", ("my_wf", {"x": 1}), {}),
    # DSL Routes (8)
    ("get_routes", "_dsl_routes", "get_routes", (), {}),
    ("list_dsl_routes", "_dsl_routes", "list_dsl_routes", (), {}),
    ("get_dsl_route", "_dsl_routes", "get_dsl_route", ("route-1",), {}),
    ("create_dsl_route", "_dsl_routes", "create_dsl_route", ("yaml: x",), {}),
    ("update_dsl_route", "_dsl_routes", "update_dsl_route", ("route-1", "yaml: y"), {}),
    ("delete_dsl_route", "_dsl_routes", "delete_dsl_route", ("route-1",), {}),
    ("validate_dsl_route", "_dsl_routes", "validate_dsl_route", ("yaml: z",), {}),
    ("diff_dsl_route", "_dsl_routes", "diff_dsl_route", ("route-1", "yaml: new"), {}),
    # Feedback (5)
    ("list_feedback_pending", "_feedback", "list_feedback_pending", (), {"limit": 10}),
    ("list_feedback_labeled", "_feedback", "list_feedback_labeled", (), {"label": "good"}),
    ("get_feedback_stats", "_feedback", "get_feedback_stats", (), {}),
    ("label_feedback", "_feedback", "label_feedback", ("doc-1",), {"label": "good"}),
    ("index_feedback_to_rag", "_feedback", "index_feedback_to_rag", (), {"limit": 50}),
    # Inventory (2)
    ("get_plugins_inventory", "_inventory", "get_plugins_inventory", (), {}),
    ("get_routes_inventory", "_inventory", "get_routes_inventory", (), {}),
    # Capability (6)
    ("get_capability_catalog", "_capability", "get_capability_catalog", (), {}),
    ("get_processor_catalog", "_capability", "get_processor_catalog", (), {"query": "x", "limit": 5}),
    ("get_audit_events", "_capability", "get_audit_events", (), {"plugin": "p1"}),
    ("get_dependency_graph", "_capability", "get_dependency_graph", (), {}),
    ("get_capability_graph", "_capability", "get_capability_graph", (), {}),
    ("scaffold_plugin", "_capability", "scaffold_plugin", ("p1",), {"dry_run": True}),
    # Logs (2)
    ("list_step_logs", "_logs", "list_step_logs", (), {"limit": 20}),
    ("get_step_detail", "_logs", "get_step_detail", ("wf-1",), {}),
]


class TestAPIClientConstruction:
    """APIClient создаёт 12 domain clients в __init__."""

    def test_creates_all_12_domain_clients(self) -> None:
        c = APIClient(base_url="http://test")
        domain_attrs = [
            "_metrics",
            "_tenants",
            "_orders",
            "_chat",
            "_flags",
            "_config",
            "_workflows",
            "_dsl_routes",
            "_feedback",
            "_inventory",
            "_capability",
            "_logs",
        ]
        for attr in domain_attrs:
            assert hasattr(c, attr), f"Missing domain client: {attr}"

    def test_domain_clients_share_base_url(self) -> None:
        c = APIClient(base_url="http://test")
        for attr in [
            "_metrics", "_tenants", "_orders", "_chat", "_flags", "_config",
            "_workflows", "_dsl_routes", "_feedback", "_inventory",
            "_capability", "_logs",
        ]:
            assert getattr(c, attr)._base_url == "http://test"


class TestAPIClientWrappers:
    """46 thin wrapper methods делегируют в domain clients."""

    @pytest.mark.parametrize(
        "wrapper_name,domain_attr,domain_method,args,kwargs",
        WRAPPER_MAPPING,
        ids=[t[0] for t in WRAPPER_MAPPING],
    )
    def test_wrapper_delegates(
        self,
        wrapper_name: str,
        domain_attr: str,
        domain_method: str,
        args: tuple,
        kwargs: dict[str, Any],
    ) -> None:
        """Каждый wrapper вызывает соответствующий domain client.

        Verifies:
        1. Wrapper вызывает domain method.
        2. Result из domain client пробрасывается через wrapper.
        3. All explicit args/kwargs values переданы в domain call.
        (Default values в wrapper signature (например, ``actor='ui'``) тоже
        передаются — но мы не проверяем их, т.к. они часть wrapper API,
        а не явных входных данных).
        """
        c = APIClient(base_url="http://test")
        domain_instance = getattr(c, domain_attr)

        # Mock the domain method
        mock_method = MagicMock(return_value={"delegated": True})
        setattr(domain_instance, domain_method, mock_method)

        # Call wrapper
        wrapper = getattr(c, wrapper_name)
        result = wrapper(*args, **kwargs)

        # Verify delegation
        assert result == {"delegated": True}
        mock_method.assert_called_once()

        # Verify each explicit arg/kwarg value reaches the domain call
        # (default values из wrapper signature не проверяем)
        actual_args, actual_kwargs = mock_method.call_args
        actual_values = list(actual_args) + list(actual_kwargs.values())
        for value in list(args) + list(kwargs.values()):
            assert value in actual_values, (
                f"Value {value!r} from wrapper not passed to domain. "
                f"actual_args={actual_args}, actual_kwargs={actual_kwargs}"
            )


class TestAPIClientBaseClass:
    """APIClient наследует BaseAPIClient (HTTP methods)."""

    def test_inherits_get(self) -> None:
        from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

        assert issubclass(APIClient, BaseAPIClient)
        assert hasattr(APIClient, "get")
        assert hasattr(APIClient, "post")
        assert hasattr(APIClient, "put")
        assert hasattr(APIClient, "patch")
        assert hasattr(APIClient, "delete")

    def test_get_uses_base_request(self) -> None:
        c = APIClient(base_url="http://test")
        with patch.object(c, "_request", return_value={"data": 1}) as req:
            result = c.get("/api/v1/foo")
        assert result == {"data": 1}
        req.assert_called_once_with("GET", "/api/v1/foo")


class TestAPIClientFactory:
    """get_api_client() factory function."""

    def test_returns_apiclient_instance(self) -> None:
        from src.frontend.streamlit_app.api_clients.generic import get_api_client

        c = get_api_client()
        assert isinstance(c, APIClient)


class TestAPIClientRegressionS46W4:
    """Regression checks для S46 W4 refactor (composition facade)."""

    def test_get_metrics_delegates_not_implements(self) -> None:
        """APIClient.get_metrics не имеет try/except, делегирует в MetricsClient."""
        c = APIClient(base_url="http://test")
        # Если бы был inline implementation, _metrics не был бы вызван
        with patch.object(c._metrics, "get_metrics", return_value={"orders": 1}) as m:
            result = c.get_metrics()
        assert result == {"orders": 1}
        m.assert_called_once_with()

    def test_get_health_delegates_not_implements(self) -> None:
        c = APIClient(base_url="http://test")
        with patch.object(c._metrics, "get_health", return_value={"status": "ok"}) as m:
            result = c.get_health()
        assert result == {"status": "ok"}
        m.assert_called_once_with()

    def test_set_override_default_actor(self) -> None:
        """APIClient.set_override использует default actor='ui'."""
        c = APIClient(base_url="http://test")
        with patch.object(c._flags, "set_override", return_value={"ok": True}) as m:
            c.set_override("f", "v")
        # Default args: tenant_id=None, actor='ui'
        m.assert_called_once_with("f", "v", None, "ui")

    def test_clear_override_default_actor(self) -> None:
        c = APIClient(base_url="http://test")
        with patch.object(c._flags, "clear_override", return_value={"ok": True}) as m:
            c.clear_override("f")
        m.assert_called_once_with("f", None, "ui")
