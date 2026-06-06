"""Tests for AdminClient composition (Sprint 46 W4 refactor).

AdminClient теперь composition facade: 8 методов делегируют в
FlagsClient / MetricsClient / ConfigClient. Эти тесты верифицируют
что delegation работает корректно, без мокания httpx (unit-level).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.frontend.streamlit_app.api_clients.admin import AdminClient


@pytest.fixture
def admin_client() -> AdminClient:
    return AdminClient(base_url="http://test")


class TestAdminClientComposition:
    """AdminClient создаёт domain clients в __init__."""

    def test_creates_flags_client(self, admin_client: AdminClient) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        assert isinstance(admin_client._flags, FlagsClient)

    def test_creates_metrics_client(self, admin_client: AdminClient) -> None:
        from src.frontend.streamlit_app.api_clients.metrics import MetricsClient

        assert isinstance(admin_client._metrics, MetricsClient)

    def test_creates_config_client(self, admin_client: AdminClient) -> None:
        from src.frontend.streamlit_app.api_clients.config import ConfigClient

        assert isinstance(admin_client._config, ConfigClient)

    def test_domain_clients_share_base_url(self, admin_client: AdminClient) -> None:
        """Все domain clients используют тот же base_url что и AdminClient."""
        assert admin_client._flags._base_url == "http://test"
        assert admin_client._metrics._base_url == "http://test"
        assert admin_client._config._base_url == "http://test"


class TestAdminClientFlagsDelegation:
    """get_flags/toggle_flag/set_override/clear_override → FlagsClient."""

    def test_get_flags_delegates(self, admin_client: AdminClient) -> None:
        expected = [{"name": "f1", "enabled": True}]
        with patch.object(
            admin_client._flags, "get_flags", return_value=expected
        ) as mock:
            result = admin_client.get_flags()
        assert result == expected
        mock.assert_called_once_with()

    def test_toggle_flag_delegates(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client._flags, "toggle_flag", return_value=True
        ) as mock:
            result = admin_client.toggle_flag("f1", True)
        assert result is True
        mock.assert_called_once_with("f1", True)

    def test_set_override_delegates_with_kwargs(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client._flags, "set_override", return_value={"ok": True}
        ) as mock:
            result = admin_client.set_override("f1", "v", tenant_id="t1", actor="a1")
        assert result == {"ok": True}
        mock.assert_called_once_with("f1", "v", tenant_id="t1", actor="a1")

    def test_clear_override_delegates_with_kwargs(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client._flags, "clear_override", return_value={"ok": True}
        ) as mock:
            result = admin_client.clear_override("f1", tenant_id="t1")
        assert result == {"ok": True}
        # actor='ui' is the default value, always passed through delegation.
        mock.assert_called_once_with("f1", tenant_id="t1", actor="ui")


class TestAdminClientMetricsDelegation:
    """get_metrics/get_health → MetricsClient."""

    def test_get_metrics_delegates(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client._metrics, "get_metrics", return_value={"orders": 42}
        ) as mock:
            result = admin_client.get_metrics()
        assert result == {"orders": 42}
        mock.assert_called_once_with()

    def test_get_health_delegates(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client._metrics, "get_health", return_value={"status": "ok"}
        ) as mock:
            result = admin_client.get_health()
        assert result == {"status": "ok"}
        mock.assert_called_once_with()


class TestAdminClientConfigDelegation:
    """get_config/get_trace_logs → ConfigClient."""

    def test_get_config_delegates(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client._config, "get_config", return_value={"version": "1.0"}
        ) as mock:
            result = admin_client.get_config()
        assert result == {"version": "1.0"}
        mock.assert_called_once_with()

    def test_get_trace_logs_delegates_with_limit(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client._config, "get_trace_logs", return_value=[{"trace": "x"}]
        ) as mock:
            result = admin_client.get_trace_logs(limit=50)
        assert result == [{"trace": "x"}]
        mock.assert_called_once_with(limit=50)


class TestAdminClientAdminOnlyMethods:
    """Admin-only methods остаются inline (нет дублей в domain clients)."""

    def test_get_ready_happy(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", return_value={"status": "ok"}):
            assert admin_client.get_ready() == {"status": "ok"}

    def test_get_ready_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", side_effect=Exception("boom")):
            result = admin_client.get_ready()
        assert result["status"] == "error"
        assert result["components"] == {}

    def test_get_capability_catalog_happy(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value={"vocabulary": ["x"]}
        ):
            assert admin_client.get_capability_catalog() == {"vocabulary": ["x"]}

    def test_get_capability_catalog_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", side_effect=Exception("boom")):
            result = admin_client.get_capability_catalog()
        assert result["vocabulary"] == []
        assert "boom" in result["error"]

    def test_get_processor_catalog_no_namespace(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value={"items": []}
        ) as get:
            admin_client.get_processor_catalog(query="q", limit=10)
        get.assert_called_once_with(
            "/api/v1/dsl/processors/search", params={"q": "q", "limit": 10}
        )

    def test_get_processor_catalog_with_namespace(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value={"items": []}
        ) as get:
            admin_client.get_processor_catalog(
                query="q", namespace="ns1", limit=20
            )
        get.assert_called_once_with(
            "/api/v1/dsl/processors/search",
            params={"q": "q", "limit": 20, "namespace": "ns1"},
        )

    def test_get_processor_catalog_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", side_effect=Exception("boom")):
            result = admin_client.get_processor_catalog()
        assert result["items"] == []
        assert result["total"] == 0
        assert "boom" in result["error"]

    def test_get_audit_events_list_response(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value=[{"event": "x"}]
        ):
            assert admin_client.get_audit_events() == [{"event": "x"}]

    def test_get_audit_events_dict_with_events(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value={"events": [{"event": "y"}]}
        ):
            assert admin_client.get_audit_events() == [{"event": "y"}]

    def test_get_audit_events_dict_without_events(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", return_value={"other": "key"}):
            assert admin_client.get_audit_events() == []

    def test_get_audit_events_with_filters(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value=[]
        ) as get:
            admin_client.get_audit_events(plugin="p1", tenant="t1", limit=50)
        get.assert_called_once_with(
            "/api/v1/admin/audit/capability",
            params={"limit": 50, "plugin": "p1", "tenant": "t1"},
        )

    def test_get_audit_events_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", side_effect=Exception("boom")):
            assert admin_client.get_audit_events() == []

    def test_get_dependency_graph_happy(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value={"nodes": ["a"], "edges": []}
        ):
            assert admin_client.get_dependency_graph() == {
                "nodes": ["a"],
                "edges": [],
            }

    def test_get_dependency_graph_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", side_effect=Exception("boom")):
            result = admin_client.get_dependency_graph()
        assert result["nodes"] == []
        assert "boom" in result["error"]

    def test_get_capability_graph_happy(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value={"nodes": ["x"]}
        ):
            assert admin_client.get_capability_graph() == {"nodes": ["x"]}

    def test_get_capability_graph_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", side_effect=Exception("boom")):
            result = admin_client.get_capability_graph()
        assert result["nodes"] == []
        assert "boom" in result["error"]

    def test_scaffold_plugin_minimal(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "post", return_value={"name": "p1", "created": True}
        ) as post:
            result = admin_client.scaffold_plugin("p1")
        assert result == {"name": "p1", "created": True}
        post.assert_called_once_with(
            "/api/v1/admin/plugins/scaffold",
            json={
                "name": "p1",
                "description": None,
                "capabilities": [],
                "features": [],
                "dry_run": True,
            },
        )

    def test_scaffold_plugin_full(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "post", return_value={"name": "p1", "created": False}
        ) as post:
            result = admin_client.scaffold_plugin(
                "p1",
                description="test plugin",
                capabilities=["cap1"],
                features=["f1", "f2"],
                dry_run=False,
            )
        assert result == {"name": "p1", "created": False}
        post.assert_called_once_with(
            "/api/v1/admin/plugins/scaffold",
            json={
                "name": "p1",
                "description": "test plugin",
                "capabilities": ["cap1"],
                "features": ["f1", "f2"],
                "dry_run": False,
            },
        )

    def test_scaffold_plugin_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "post", side_effect=Exception("boom")):
            result = admin_client.scaffold_plugin("p1")
        assert result["name"] == "p1"
        assert result["created"] is False
        assert "boom" in result["error"]

    def test_get_langgraph_sessions_happy(self, admin_client: AdminClient) -> None:
        with patch.object(
            admin_client, "get", return_value={"sessions": ["s1"], "count": 1}
        ) as get:
            result = admin_client.get_langgraph_sessions(limit=10, offset=5)
        assert result == {"sessions": ["s1"], "count": 1}
        get.assert_called_once_with(
            "/api/v1/admin/langgraph/checkpoints",
            params={"limit": 10, "offset": 5},
        )

    def test_get_langgraph_sessions_exception(self, admin_client: AdminClient) -> None:
        with patch.object(admin_client, "get", side_effect=Exception("boom")):
            result = admin_client.get_langgraph_sessions()
        assert result["sessions"] == []
        assert result["count"] == 0
        assert "boom" in result["error"]


class TestAdminClientKwargPropagation:
    """kwargs пробрасываются в domain clients (token, max_retries, etc.)."""

    def test_token_propagated_to_domain_clients(self) -> None:
        c = AdminClient(base_url="http://test", token="jwt_xyz")
        assert c._flags._token == "jwt_xyz"
        assert c._metrics._token == "jwt_xyz"
        assert c._config._token == "jwt_xyz"

    def test_max_retries_propagated(self) -> None:
        c = AdminClient(base_url="http://test", max_retries=5)
        assert c._flags._max_retries == 5
        assert c._metrics._max_retries == 5
        assert c._config._max_retries == 5

    def test_retry_overrides_propagated(self) -> None:
        c = AdminClient(
            base_url="http://test",
            retry_overrides={"/api/v1/admin/feature-flags": 7},
        )
        assert c._flags._retry_overrides == {"/api/v1/admin/feature-flags": 7}
        assert c._metrics._retry_overrides == {"/api/v1/admin/feature-flags": 7}
        assert c._config._retry_overrides == {"/api/v1/admin/feature-flags": 7}

    def test_jitter_ratio_propagated(self) -> None:
        c = AdminClient(base_url="http://test", jitter_ratio=0.3)
        assert c._flags._jitter_ratio == 0.3
        assert c._metrics._jitter_ratio == 0.3
        assert c._config._jitter_ratio == 0.3
