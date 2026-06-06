"""Coverage tests для 6 small api_clients (Sprint 47 W1).

Targets:
- config.py: 46.7% → 100% (2 methods)
- inventory.py: 46.7% → 100% (2 methods)
- orders.py: 69.2% → 100% (4 methods)
- chat.py: 71.4% → 100% (1 method, multiple paths)
- metrics.py: 77.8% → 100% (2 methods)
- tenants.py: 77.8% → 100% (2 methods)
"""

from __future__ import annotations

from unittest.mock import patch


# ============================================================
# ConfigClient tests
# ============================================================


class TestConfigClient:
    """config.py — admin config + trace-logs."""

    def test_get_config_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.config import ConfigClient

        c = ConfigClient()
        with patch.object(c, "_request", return_value={"version": "1.0"}) as req:
            assert c.get_config() == {"version": "1.0"}
        req.assert_called_once_with("GET", "/api/v1/admin/config")

    def test_get_config_exception_returns_empty_dict(self) -> None:
        from src.frontend.streamlit_app.api_clients.config import ConfigClient

        c = ConfigClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_config() == {}

    def test_get_trace_logs_default_limit(self) -> None:
        from src.frontend.streamlit_app.api_clients.config import ConfigClient

        c = ConfigClient()
        with patch.object(c, "_request", return_value=[{"trace": "x"}]) as req:
            assert c.get_trace_logs() == [{"trace": "x"}]
        req.assert_called_once_with(
            "GET", "/api/v1/admin/trace-logs", params={"limit": 100}
        )

    def test_get_trace_logs_custom_limit(self) -> None:
        from src.frontend.streamlit_app.api_clients.config import ConfigClient

        c = ConfigClient()
        with patch.object(c, "_request", return_value=[]) as req:
            c.get_trace_logs(limit=50)
        req.assert_called_once_with(
            "GET", "/api/v1/admin/trace-logs", params={"limit": 50}
        )

    def test_get_trace_logs_exception_returns_empty_list(self) -> None:
        from src.frontend.streamlit_app.api_clients.config import ConfigClient

        c = ConfigClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_trace_logs() == []


# ============================================================
# InventoryClient tests
# ============================================================


class TestInventoryClient:
    """inventory.py — plugins + routes inventory."""

    def test_get_plugins_inventory_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.inventory import InventoryClient

        c = InventoryClient()
        with patch.object(
            c, "_request", return_value={"enabled": True, "plugins": ["p1"]}
        ) as req:
            result = c.get_plugins_inventory()
        assert result == {"enabled": True, "plugins": ["p1"]}
        req.assert_called_once_with("GET", "/api/v1/plugins/inventory")

    def test_get_plugins_inventory_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.inventory import InventoryClient

        c = InventoryClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            result = c.get_plugins_inventory()
        assert result["enabled"] is False
        assert result["plugins"] == []
        assert "boom" in result["reason"]

    def test_get_routes_inventory_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.inventory import InventoryClient

        c = InventoryClient()
        with patch.object(
            c, "_request", return_value={"enabled": True, "routes": ["r1"]}
        ) as req:
            result = c.get_routes_inventory()
        assert result == {"enabled": True, "routes": ["r1"]}
        req.assert_called_once_with("GET", "/api/v1/routes/inventory")

    def test_get_routes_inventory_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.inventory import InventoryClient

        c = InventoryClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            result = c.get_routes_inventory()
        assert result["enabled"] is False
        assert result["routes"] == []
        assert "boom" in result["reason"]


# ============================================================
# OrdersClient tests
# ============================================================


class TestOrdersClient:
    """orders.py — orders CRUD."""

    def test_get_orders_defaults(self) -> None:
        from src.frontend.streamlit_app.api_clients.orders import OrdersClient

        c = OrdersClient()
        with patch.object(c, "_request", return_value={"items": []}) as req:
            result = c.get_orders()
        assert result == {"items": []}
        req.assert_called_once_with(
            "GET", "/api/v1/orders/all/", params={"page": 1, "size": 50}
        )

    def test_get_orders_custom_pagination(self) -> None:
        from src.frontend.streamlit_app.api_clients.orders import OrdersClient

        c = OrdersClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.get_orders(page=3, size=100)
        req.assert_called_once_with(
            "GET", "/api/v1/orders/all/", params={"page": 3, "size": 100}
        )

    def test_create_order(self) -> None:
        from src.frontend.streamlit_app.api_clients.orders import OrdersClient

        c = OrdersClient()
        data = {"name": "Widget", "price": 9.99}
        with patch.object(c, "_request", return_value={"id": 1}) as req:
            result = c.create_order(data)
        assert result == {"id": 1}
        req.assert_called_once_with("POST", "/api/v1/orders/create/", json=data)

    def test_update_order(self) -> None:
        from src.frontend.streamlit_app.api_clients.orders import OrdersClient

        c = OrdersClient()
        data = {"name": "Updated"}
        with patch.object(c, "_request", return_value={"id": 1, "name": "Updated"}) as req:
            result = c.update_order(42, data)
        assert result == {"id": 1, "name": "Updated"}
        req.assert_called_once_with(
            "PUT", "/api/v1/orders/update/42", json=data
        )

    def test_delete_order(self) -> None:
        from src.frontend.streamlit_app.api_clients.orders import OrdersClient

        c = OrdersClient()
        with patch.object(c, "_request", return_value=None) as req:
            result = c.delete_order(42)
        assert result is None
        req.assert_called_once_with("DELETE", "/api/v1/orders/delete/42")


# ============================================================
# ChatClient tests
# ============================================================


class TestChatClient:
    """chat.py — AI chat endpoint."""

    def test_chat_dict_response_extracts_response(self) -> None:
        from src.frontend.streamlit_app.api_clients.chat import ChatClient

        c = ChatClient()
        with patch.object(
            c, "_request", return_value={"response": "Hello!", "session_id": "s1"}
        ):
            assert c.chat("hi") == "Hello!"

    def test_chat_string_response(self) -> None:
        from src.frontend.streamlit_app.api_clients.chat import ChatClient

        c = ChatClient()
        with patch.object(c, "_request", return_value="plain string"):
            assert c.chat("hi") == "plain string"

    def test_chat_dict_without_response_returns_str(self) -> None:
        """Если dict не содержит 'response', fallback на str(result)."""
        from src.frontend.streamlit_app.api_clients.chat import ChatClient

        c = ChatClient()
        with patch.object(c, "_request", return_value={"other_key": "value"}):
            result = c.chat("hi")
        # str({"other_key": "value"}) = "{'other_key': 'value'}"
        assert "other_key" in result
        assert "value" in result

    def test_chat_passes_session_id(self) -> None:
        from src.frontend.streamlit_app.api_clients.chat import ChatClient

        c = ChatClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.chat("hi", session_id="my_session")
        req.assert_called_once_with(
            "POST",
            "/api/v1/ai/chat",
            json={"message": "hi", "session_id": "my_session"},
        )

    def test_chat_default_session_id(self) -> None:
        from src.frontend.streamlit_app.api_clients.chat import ChatClient

        c = ChatClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.chat("hi")
        req.assert_called_once_with(
            "POST",
            "/api/v1/ai/chat",
            json={"message": "hi", "session_id": "default"},
        )


# ============================================================
# MetricsClient tests
# ============================================================


class TestMetricsClient:
    """metrics.py — metrics + health."""

    def test_get_metrics_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.metrics import MetricsClient

        c = MetricsClient()
        with patch.object(c, "_request", return_value={"orders": 42}) as req:
            result = c.get_metrics()
        assert result == {"orders": 42}
        req.assert_called_once_with("GET", "/api/v1/admin/metrics")

    def test_get_metrics_exception_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.metrics import MetricsClient

        c = MetricsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_metrics() == {}

    def test_get_health_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.metrics import MetricsClient

        c = MetricsClient()
        with patch.object(c, "_request", return_value={"status": "ok"}) as req:
            result = c.get_health()
        assert result == {"status": "ok"}
        req.assert_called_once_with("GET", "/api/v1/health/components")

    def test_get_health_exception_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.metrics import MetricsClient

        c = MetricsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_health() == {}


# ============================================================
# TenantsClient tests
# ============================================================


class TestTenantsClient:
    """tenants.py — admin tenants list + detail."""

    def test_get_tenants_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.tenants import TenantsClient

        c = TenantsClient()
        with patch.object(
            c, "_request", return_value={"tenants": ["t1"], "total": 1}
        ) as req:
            result = c.get_tenants()
        assert result == {"tenants": ["t1"], "total": 1}
        req.assert_called_once_with("GET", "/api/v1/admin/tenants")

    def test_get_tenants_propagates_exception(self) -> None:
        """TenantsClient не имеет graceful fallback — exception пробрасывается."""
        from src.frontend.streamlit_app.api_clients.tenants import TenantsClient

        c = TenantsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            with __import__("pytest").raises(Exception, match="boom"):
                c.get_tenants()

    def test_get_tenant_detail_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.tenants import TenantsClient

        c = TenantsClient()
        with patch.object(
            c, "_request", return_value={"id": "t1", "audit": []}
        ) as req:
            result = c.get_tenant_detail("t1")
        assert result == {"id": "t1", "audit": []}
        req.assert_called_once_with("GET", "/api/v1/admin/tenants/t1")

    def test_get_tenant_detail_propagates_exception(self) -> None:
        """TenantsClient не имеет graceful fallback — exception пробрасывается."""
        from src.frontend.streamlit_app.api_clients.tenants import TenantsClient

        c = TenantsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            with __import__("pytest").raises(Exception, match="boom"):
                c.get_tenant_detail("missing")
