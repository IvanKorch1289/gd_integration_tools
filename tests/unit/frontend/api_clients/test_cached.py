# ruff: noqa: S101
"""Unit tests для src.frontend.streamlit_app.api_clients.cached (S171 W2/M3).

Тестируем:
- Module-level constants (TTL_*) from env vars
- cached_get_metrics/orders возвращают dict/list при success
- Graceful fallback {} / [] при exception

NOTE: clear_api_cache() тестируется отдельно (имеет test isolation issues
с importlib.reload).
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_streamlit() -> MagicMock:
    """Mock streamlit для каждого теста (isolation от test pollution)."""
    sm = ModuleType("streamlit")
    sm.set_page_config = MagicMock()
    sm.cache_data = MagicMock(
        side_effect=lambda *args, **kwargs: lambda f: f
    )
    sm.cache_data.clear = MagicMock()
    sys.modules["streamlit"] = sm
    yield sm


def _get_cached_module():
    """Lazy import (handles reload correctly)."""
    from src.frontend.streamlit_app.api_clients import cached as cm
    return cm


def test_ttl_constants_default(mock_streamlit: MagicMock) -> None:
    """TTL defaults: METRICS=10, HEALTH=5, ORDERS=15."""
    cm = _get_cached_module()
    assert cm.TTL_METRICS == 10
    assert cm.TTL_HEALTH == 5
    assert cm.TTL_ORDERS == 15


def test_ttl_constants_from_env(
    monkeypatch: pytest.MonkeyPatch, mock_streamlit: MagicMock
) -> None:
    """TTL overridable via env vars."""
    monkeypatch.setenv("STREAMLIT_CACHE_TTL_METRICS", "30")
    monkeypatch.setenv("STREAMLIT_CACHE_TTL_HEALTH", "60")
    monkeypatch.setenv("STREAMLIT_CACHE_TTL_ORDERS", "120")

    cm = _get_cached_module()
    fresh = importlib.reload(cm)
    assert fresh.TTL_METRICS == 30
    assert fresh.TTL_HEALTH == 60
    assert fresh.TTL_ORDERS == 120


def test_cached_get_metrics_success(mock_streamlit: MagicMock) -> None:
    """cached_get_metrics returns dict on success."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = {"routes_total": 100}
        result = cm.cached_get_metrics()
        assert isinstance(result, dict)
        assert result["routes_total"] == 100


def test_cached_get_metrics_exception(mock_streamlit: MagicMock) -> None:
    """cached_get_metrics returns {} on exception (graceful fallback)."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.side_effect = ConnectionError("Backend down")
        result = cm.cached_get_metrics()
        assert result == {}


def test_cached_get_health_success(mock_streamlit: MagicMock) -> None:
    """cached_get_health returns dict on success."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = {"postgres": True, "redis": True}
        result = cm.cached_get_health()
        assert isinstance(result, dict)


def test_cached_get_health_exception(mock_streamlit: MagicMock) -> None:
    """cached_get_health returns {} on exception."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.side_effect = TimeoutError("Slow backend")
        result = cm.cached_get_health()
        assert result == {}


def test_cached_get_orders_success(mock_streamlit: MagicMock) -> None:
    """cached_get_orders returns list on success."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = [{"id": 1}, {"id": 2}]
        result = cm.cached_get_orders()
        assert isinstance(result, list)
        assert len(result) == 2


def test_cached_get_orders_exception(mock_streamlit: MagicMock) -> None:
    """cached_get_orders returns [] on exception."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.side_effect = RuntimeError("500 Internal")
        result = cm.cached_get_orders()
        assert result == []


def test_cached_get_orders_pagination(mock_streamlit: MagicMock) -> None:
    """cached_get_orders forwards page/size params."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = []
        cm.cached_get_orders(page=3, size=25)
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/orders/all/"
        assert call_args[1]["params"]["page"] == 3
        assert call_args[1]["params"]["size"] == 25
