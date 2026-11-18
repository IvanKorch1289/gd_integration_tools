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
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

#: Настоящий streamlit (зафиксирован до подмены в fixture).
_REAL_STREAMLIT = importlib.import_module("streamlit")


def _cache_data_mock(*_args: object, **_kwargs: object) -> Callable[..., Any]:
    """Мок ``st.cache_data`` — возвращает обёртку, как настоящий Streamlit.

    Настоящий ``st.cache_data`` возвращает ``CachedFunc``-обёртку, а не
    саму функцию. Плоский мок ``lambda f: f`` ломает декораторы, которые
    подставляют в ключ кэша дополнительный аргумент (scope пользователя).
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper.clear = MagicMock()  # type: ignore[attr-defined]
        return wrapper

    return decorator


@pytest.fixture(autouse=True)
def mock_streamlit() -> Iterator[ModuleType]:
    """Mock streamlit для каждого теста (isolation от test pollution).

    Мок обязательно восстанавливается: без этого ``sys.modules['streamlit']``
    остаётся подменённым для всех следующих тестов в сессии (ломает
    ``st.session_state`` в ``shared/auth_state.py`` и любые страницы портала).

    ``st.cache_data`` в ``hooks/cache.py`` привязан к НАСТОЯЩЕМУ streamlit
    (модуль импортирован раньше мока) → глобальный кэш очищается явно, иначе
    результат одного теста утекает в следующий.
    """
    _REAL_STREAMLIT.cache_data.clear()
    sm = ModuleType("streamlit")
    setattr(sm, "set_page_config", MagicMock())
    cache_data_mock = MagicMock(side_effect=_cache_data_mock)
    setattr(cache_data_mock, "clear", MagicMock())
    setattr(sm, "cache_data", cache_data_mock)
    setattr(sm, "session_state", {})
    original = sys.modules.get("streamlit")
    sys.modules["streamlit"] = sm
    yield sm
    _REAL_STREAMLIT.cache_data.clear()
    if original is not None:
        sys.modules["streamlit"] = original
    else:
        sys.modules.pop("streamlit", None)


def _get_cached_module():
    """Lazy import (handles reload correctly)."""
    from src.frontend.streamlit_app.api_clients import cached as cm

    return cm


def test_ttl_constants_default(mock_streamlit: ModuleType) -> None:
    """TTL defaults: METRICS=10, HEALTH=5, ORDERS=15."""
    cm = _get_cached_module()
    assert cm.TTL_METRICS == 10
    assert cm.TTL_HEALTH == 5
    assert cm.TTL_ORDERS == 15


def test_ttl_constants_from_env(
    monkeypatch: pytest.MonkeyPatch, mock_streamlit: ModuleType
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


def test_cached_get_metrics_success(mock_streamlit: ModuleType) -> None:
    """cached_get_metrics returns dict on success."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = {"routes_total": 100}
        result = cm.cached_get_metrics()
        assert isinstance(result, dict)
        assert result["routes_total"] == 100


def test_cached_get_metrics_exception(mock_streamlit: ModuleType) -> None:
    """cached_get_metrics returns {} on exception (graceful fallback)."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.side_effect = ConnectionError("Backend down")
        result = cm.cached_get_metrics()
        assert result == {}


def test_cached_get_health_success(mock_streamlit: ModuleType) -> None:
    """cached_get_health returns dict on success."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = {"postgres": True, "redis": True}
        result = cm.cached_get_health()
        assert isinstance(result, dict)


def test_cached_get_health_exception(mock_streamlit: ModuleType) -> None:
    """cached_get_health returns {} on exception."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.side_effect = TimeoutError("Slow backend")
        result = cm.cached_get_health()
        assert result == {}


def test_cached_get_orders_success(mock_streamlit: ModuleType) -> None:
    """cached_get_orders returns list on success."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = [{"id": 1}, {"id": 2}]
        result = cm.cached_get_orders()
        assert isinstance(result, list)
        assert len(result) == 2


def test_cached_get_orders_exception(mock_streamlit: ModuleType) -> None:
    """cached_get_orders returns [] on exception."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.side_effect = RuntimeError("500 Internal")
        result = cm.cached_get_orders()
        assert result == []


def test_cached_get_orders_pagination(mock_streamlit: ModuleType) -> None:
    """cached_get_orders forwards page/size params."""
    cm = _get_cached_module()
    with patch.object(cm.BaseAPIClient, "_request") as mock_request:
        mock_request.return_value = []
        cm.cached_get_orders(page=3, size=25)
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/api/v1/order/all/"
        assert call_args[1]["params"]["page"] == 3
        assert call_args[1]["params"]["size"] == 25
