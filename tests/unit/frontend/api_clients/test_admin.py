"""Tests for AdminClient (Sprint 45 W3 — coverage uplift).

admin.py was 19.8% covered (96 stmt, 75 miss). These tests exercise
the 16 admin methods with mocked httpx.Client.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _mock_response(status: int = 200, payload: Any = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.headers = {"content-type": "application/json"}
    mock.json.return_value = payload
    return mock


def _patched_client(mock_response: Any) -> Any:
    """Context manager: patch httpx.Client with given response.

    Returns MagicMock representing httpx.Client class.
    Mock structure:
        httpx.Client() → mock_client
        mock_client.__enter__() → mock_client (self)
        mock_client.request(method, url, **kwargs) → mock_response
    """
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.request.return_value = mock_response
    return patch("httpx.Client", return_value=mock_client)


@pytest.fixture
def admin_client() -> Any:
    """AdminClient with base_url overridden for tests."""
    from src.frontend.streamlit_app.api_clients.admin import AdminClient

    return AdminClient(base_url="http://test")


class TestAdminClientMetrics:
    """get_metrics, get_health."""

    def test_get_metrics(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"orders": 42, "users": 100})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert admin_client.get_metrics() == {"orders": 42, "users": 100}

    def test_get_health(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"status": "ok", "components": []})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert admin_client.get_health()["status"] == "ok"


class TestAdminClientFlags:
    """get_flags, toggle_flag, set_override, clear_override."""

    def test_get_flags(self, admin_client: Any) -> None:
        mock = _mock_response(payload=[{"name": "f1", "enabled": True}])
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            flags = admin_client.get_flags()
            assert len(flags) == 1
            assert flags[0]["name"] == "f1"

    def test_toggle_flag(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"ok": True})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert admin_client.toggle_flag("f1", True) is True

    def test_set_override(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"ok": True})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert admin_client.set_override(
                "f1", True
            ) is True or admin_client.set_override("f1", True) == {"ok": True}

    def test_clear_override(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"ok": True})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = admin_client.clear_override("f1")
            assert result is not None


class TestAdminClientConfig:
    """get_config, get_trace_logs."""

    def test_get_config(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"version": "1.0"})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert admin_client.get_config()["version"] == "1.0"

    def test_get_trace_logs(self, admin_client: Any) -> None:
        mock = _mock_response(payload=[{"id": 1, "msg": "test"}])
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            logs = admin_client.get_trace_logs(limit=10)
            assert isinstance(logs, list)
            assert logs[0]["id"] == 1


class TestAdminClientCatalog:
    """get_capability_catalog, get_processor_catalog, get_audit_events, etc."""

    def test_get_capability_catalog(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"catalog": []})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert "catalog" in admin_client.get_capability_catalog()

    def test_get_processor_catalog(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"items": [], "total": 0})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = admin_client.get_processor_catalog(query="split")
            assert "items" in result

    def test_get_audit_events(self, admin_client: Any) -> None:
        mock = _mock_response(payload=[{"id": 1, "action": "create"}])
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            events = admin_client.get_audit_events(limit=50)
            assert len(events) == 1

    def test_get_dependency_graph(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"nodes": [], "edges": []})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert "nodes" in admin_client.get_dependency_graph()

    def test_get_capability_graph(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"nodes": [], "edges": []})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert "nodes" in admin_client.get_capability_graph()


class TestAdminClientMisc:
    """scaffold_plugin, get_ready, get_langgraph_sessions."""

    def test_scaffold_plugin(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"name": "test", "created": True})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = admin_client.scaffold_plugin("test", dry_run=True)
            assert result["name"] == "test"

    def test_get_ready(self, admin_client: Any) -> None:
        mock = _mock_response(payload={"ready": True})
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert admin_client.get_ready()["ready"] is True

    def test_get_langgraph_sessions(self, admin_client: Any) -> None:
        mock = _mock_response(payload=[{"session_id": "s1"}])
        with _patched_client(mock) as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            sessions = admin_client.get_langgraph_sessions()
            assert len(sessions) == 1


class TestAdminClientErrorHandling:
    """HTTP errors → graceful fallback (catches and returns safe default)."""

    def test_5xx_returns_safe_default(self, admin_client: Any) -> None:
        """get_audit_events catches all exceptions → returns []."""
        import httpx

        with patch("httpx.Client") as patched:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.side_effect = httpx.ConnectError("down")
            patched.return_value = mock_client

            # get_audit_events catches exception → returns []
            assert admin_client.get_audit_events(limit=10) == []
