"""Tests for WorkflowsClient + CapabilityClient (Sprint 45 W3 — coverage uplift)."""

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


# ─── WorkflowsClient ──────────────────────────────────────────────────────


@pytest.fixture
def workflows_client() -> Any:
    from src.frontend.streamlit_app.api_clients.workflows import WorkflowsClient

    return WorkflowsClient(base_url="http://test")


class TestWorkflowsClient:
    def test_list_workflows(self, workflows_client: Any) -> None:
        mock = _mock_response(
            payload=[{"instance_id": "wf-1", "status": "ok"}]
        )
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = workflows_client.list_workflows()
            assert len(result) == 1
            assert result[0]["instance_id"] == "wf-1"

    def test_list_workflows_with_filters(self, workflows_client: Any) -> None:
        mock = _mock_response(payload=[])
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            workflows_client.list_workflows(
                status="ok", workflow_name="x", tenant_id="t1", limit=5
            )
            call = patched.return_value.__enter__.return_value.request.call_args
            assert call.kwargs["params"]["status"] == "ok"
            assert call.kwargs["params"]["workflow_name"] == "x"
            assert call.kwargs["params"]["tenant_id"] == "t1"
            assert call.kwargs["params"]["limit"] == 5

    def test_get_workflow(self, workflows_client: Any) -> None:
        mock = _mock_response(payload={"instance_id": "wf-1", "status": "ok"})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = workflows_client.get_workflow("wf-1")
            assert result["instance_id"] == "wf-1"

    def test_get_workflow_events(self, workflows_client: Any) -> None:
        mock = _mock_response(payload=[{"seq": 1, "type": "step"}])
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            events = workflows_client.get_workflow_events("wf-1", after_seq=0, limit=50)
            assert len(events) == 1

    def test_retry_workflow(self, workflows_client: Any) -> None:
        mock = _mock_response(status=200, payload={})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert workflows_client.retry_workflow("wf-1") is True

    def test_cancel_workflow(self, workflows_client: Any) -> None:
        mock = _mock_response(status=200, payload={})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert workflows_client.cancel_workflow("wf-1", reason="user") is True

    def test_resume_workflow(self, workflows_client: Any) -> None:
        mock = _mock_response(status=200, payload={})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert workflows_client.resume_workflow("wf-1") is True

    def test_trigger_workflow(self, workflows_client: Any) -> None:
        mock = _mock_response(payload={"instance_id": "wf-new"})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = workflows_client.trigger_workflow(
                "test_wf", {"key": "val"}, wait=False
            )
            assert result["instance_id"] == "wf-new"

    def test_5xx_returns_empty(self, workflows_client: Any) -> None:
        """5xx → exception caught → returns [] / None / False."""
        import httpx

        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.side_effect = (
                httpx.ConnectError("down")
            )
            # list_workflows catches and returns []
            assert workflows_client.list_workflows() == []
            # get_workflow catches and returns None
            assert workflows_client.get_workflow("wf-1") is None
            # retry/cancel/resume catch and return False
            assert workflows_client.retry_workflow("wf-1") is False
            assert workflows_client.cancel_workflow("wf-1") is False
            assert workflows_client.resume_workflow("wf-1") is False


# ─── CapabilityClient ─────────────────────────────────────────────────────


@pytest.fixture
def capability_client() -> Any:
    from src.frontend.streamlit_app.api_clients.capability import CapabilityClient

    return CapabilityClient(base_url="http://test")


class TestCapabilityClient:
    def test_get_capability_catalog(self, capability_client: Any) -> None:
        mock = _mock_response(payload={"catalog": [], "vocabulary": []})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = capability_client.get_capability_catalog()
            assert "catalog" in result

    def test_get_processor_catalog(self, capability_client: Any) -> None:
        mock = _mock_response(payload={"items": [], "total": 0, "query": "x"})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = capability_client.get_processor_catalog(query="split")
            assert result["total"] == 0

    def test_get_processor_catalog_with_namespace(self, capability_client: Any) -> None:
        mock = _mock_response(payload={"items": []})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            capability_client.get_processor_catalog(
                query="x", namespace="routing", limit=10
            )
            call = patched.return_value.__enter__.return_value.request.call_args
            assert call.kwargs["params"]["namespace"] == "routing"

    def test_get_audit_events_list(self, capability_client: Any) -> None:
        mock = _mock_response(payload=[{"id": 1}])
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            events = capability_client.get_audit_events(limit=10)
            assert isinstance(events, list)

    def test_get_audit_events_dict(self, capability_client: Any) -> None:
        """When response is dict, extract 'events' key."""
        mock = _mock_response(payload={"events": [{"id": 1}]})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            events = capability_client.get_audit_events(limit=10)
            assert len(events) == 1

    def test_get_dependency_graph(self, capability_client: Any) -> None:
        mock = _mock_response(payload={"nodes": [], "edges": []})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert "nodes" in capability_client.get_dependency_graph()

    def test_get_capability_graph(self, capability_client: Any) -> None:
        mock = _mock_response(payload={"nodes": [], "edges": []})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            assert "nodes" in capability_client.get_capability_graph()

    def test_scaffold_plugin(self, capability_client: Any) -> None:
        mock = _mock_response(payload={"name": "p1", "created": True})
        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.return_value = mock
            result = capability_client.scaffold_plugin("p1", dry_run=True)
            assert result["name"] == "p1"

    def test_5xx_returns_safe_fallback(self, capability_client: Any) -> None:
        """5xx/transport errors → method-specific fallback (dict with error key)."""
        import httpx

        with patch("httpx.Client") as patched:
            patched.return_value.__enter__.return_value.request.side_effect = (
                httpx.ConnectError("down")
            )
            catalog = capability_client.get_capability_catalog()
            assert "error" in catalog
            assert capability_client.get_audit_events() == []
            assert capability_client.get_dependency_graph() == {
                "nodes": [],
                "edges": [],
                "error": catalog["error"],  # same fallback shape
            }
            assert capability_client.get_processor_catalog() == {
                "query": "",
                "items": [],
                "total": 0,
                "error": catalog["error"],
            }
