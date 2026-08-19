"""Regression tests для HTTP client methods добавленных в cycle 208.

Защищает от регрессии:
- ``AdminClient.list_workflow_templates()`` (33_DSL_Шаблоны.py миграция)
- ``WorkflowsClient.get_workflow_version_history(wf_id)`` (18_Версионирование.py)
- ``WorkflowsClient.list_all_workflow_ids(limit=N)`` (15_Оценка_стоимости.py)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _mock_response(payload: Any) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.headers = {"content-type": "application/json"}
    mock.json.return_value = payload
    return mock


@pytest.fixture
def admin_client() -> Any:
    from src.frontend.streamlit_app.api_clients.admin import AdminClient

    return AdminClient(base_url="http://test")


@pytest.fixture
def workflows_client() -> Any:
    from src.frontend.streamlit_app.api_clients.workflows import WorkflowsClient

    return WorkflowsClient(base_url="http://test")


# ─── AdminClient.list_workflow_templates ──────────────────────────────


class TestAdminListWorkflowTemplates:
    """Cycle 208: AdminClient.list_workflow_templates() (33_DSL_Шаблоны миграция)."""

    def test_returns_list_on_200(
        self, admin_client: Any,
    ) -> None:
        """200 + list payload → return list as-is."""
        with patch.object(
            admin_client, "_request", return_value=[{"name": "customer_onboarding"}]
        ) as mock_req:
            result = admin_client.list_workflow_templates()

        assert result == [{"name": "customer_onboarding"}]
        mock_req.assert_called_once_with("GET", "/api/v1/admin/workflow-templates")

    def test_returns_empty_on_non_list(
        self, admin_client: Any,
    ) -> None:
        """Non-list response (e.g. dict error) → return []."""
        with patch.object(
            admin_client, "_request", return_value={"error": "x"}
        ):
            result = admin_client.list_workflow_templates()
        assert result == []

    def test_returns_empty_on_connection_error(
        self, admin_client: Any,
    ) -> None:
        """Connection error → return [] (не пробрасывается)."""
        with patch.object(
            admin_client, "_request", side_effect=ConnectionError("refused")
        ):
            result = admin_client.list_workflow_templates()
        assert result == []


# ─── WorkflowsClient.get_workflow_version_history ───────────────────


class TestWorkflowsGetVersionHistory:
    """Cycle 208: get_workflow_version_history() (18_Версионирование миграция)."""

    def test_returns_list_on_200(
        self, workflows_client: Any,
    ) -> None:
        """200 + list payload → return list as-is."""
        with patch.object(
            workflows_client, "_request",
            return_value=[{"semver": "1.0.0"}, {"semver": "1.0.1"}],
        ) as mock_req:
            result = workflows_client.get_workflow_version_history("credit_assessment")

        assert result == [{"semver": "1.0.0"}, {"semver": "1.0.1"}]
        mock_req.assert_called_once_with(
            "GET", "/api/v1/admin/workflow-versioning/credit_assessment/history"
        )

    def test_returns_empty_on_non_list(
        self, workflows_client: Any,
    ) -> None:
        """Non-list response → []."""
        with patch.object(
            workflows_client, "_request", return_value={"detail": "Not Found"}
        ):
            result = workflows_client.get_workflow_version_history("nonexistent")
        assert result == []

    def test_returns_empty_on_runtime_error(
        self, workflows_client: Any,
    ) -> None:
        """RuntimeError → [] (swallowed)."""
        with patch.object(
            workflows_client, "_request", side_effect=RuntimeError("boom")
        ):
            result = workflows_client.get_workflow_version_history("x")
        assert result == []


# ─── WorkflowsClient.list_all_workflow_ids ─────────────────────────


class TestWorkflowsListAllIds:
    """Cycle 208: list_all_workflow_ids() (15_Оценка_стоимости миграция)."""

    def test_extracts_workflow_names(
        self, workflows_client: Any,
    ) -> None:
        """Из list[dict] извлекает 'workflowName' field в list[str]."""
        payload = [
            {"id": "a", "workflowName": "credit_assessment"},
            {"id": "b", "workflowName": "rag_augmented_saga"},
            {"id": "c", "workflowName": "code_interpreter_loop"},
        ]
        with patch.object(
            workflows_client, "_request", return_value=payload
        ) as mock_req:
            result = workflows_client.list_all_workflow_ids(limit=1000)

        assert result == [
            "credit_assessment", "rag_augmented_saga", "code_interpreter_loop",
        ]
        mock_req.assert_called_once_with(
            "GET", "/api/v1/admin/workflows", params={"limit": 1000}
        )

    def test_custom_limit(
        self, workflows_client: Any,
    ) -> None:
        """Custom limit передан как query param."""
        with patch.object(
            workflows_client, "_request", return_value=[]
        ) as mock_req:
            result = workflows_client.list_all_workflow_ids(limit=50)

        assert result == []
        mock_req.assert_called_once_with(
            "GET", "/api/v1/admin/workflows", params={"limit": 50}
        )

    def test_filters_empty_workflow_names(
        self, workflows_client: Any,
    ) -> None:
        """Items без 'workflowName' исключаются из результата."""
        payload = [
            {"id": "a", "workflowName": "good"},
            {"id": "b"},  # no workflowName
            {"id": "c", "workflowName": ""},  # empty
        ]
        with patch.object(workflows_client, "_request", return_value=payload):
            result = workflows_client.list_all_workflow_ids()
        assert result == ["good"]

    def test_returns_empty_on_non_list(
        self, workflows_client: Any,
    ) -> None:
        """Non-list response → []."""
        with patch.object(workflows_client, "_request", return_value={}):
            result = workflows_client.list_all_workflow_ids()
        assert result == []

    def test_returns_empty_on_connection_error(
        self, workflows_client: Any,
    ) -> None:
        """Connection error → []."""
        with patch.object(
            workflows_client, "_request", side_effect=ConnectionError("boom")
        ):
            result = workflows_client.list_all_workflow_ids()
        assert result == []
