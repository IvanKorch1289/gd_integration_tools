"""S175 W2: tests для 90_Реестр_Маршрутов.py (Registry Explorer page).

Проверяем:
- Файл существует.
- Использует core.registry_explorer (route/connector/ActionEntry).
- ``_seed_explorer`` заполняет routes + connectors.
- ``_seed_explorer`` корректно обрабатывает пустые inventory responses.
- RegistryExplorer search/filter logic для UI работает end-to-end.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

# Mock streamlit (full surface) BEFORE any imports.
_streamlit_mock = ModuleType("streamlit")
for attr in [
    "set_page_config",
    "header",
    "metric",
    "divider",
    "subheader",
    "info",
    "warning",
    "caption",
    "tabs",
    "columns",
    "button",
    "rerun",
    "spinner",
    "dataframe",
    "json",
    "selectbox",
    "text_input",
    "multiselect",
    "expander",
]:
    setattr(_streamlit_mock, attr, MagicMock())


# cache_data / cache_resource are DECORATORS (not MagicMock instances).
# Using a real function-decorator mock avoids "module has no attribute" errors.
def _passthrough_decorator(
    *_args: object, **_kwargs: object
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Return a no-op decorator."""

    def _decorator(fn: Callable[..., object]) -> Callable[..., object]:
        return fn

    return _decorator


_streamlit_mock.cache_data = _passthrough_decorator
_streamlit_mock.cache_resource = _passthrough_decorator
_streamlit_mock.tabs = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])


# st.columns is called with different sizes depending on context.
# Use side_effect to return a variable-length list.
def _columns_mock(spec):
    if isinstance(spec, int):
        n = spec
    elif hasattr(spec, "__len__"):
        n = len(spec)
    else:
        n = 1
    return [MagicMock() for _ in range(n)]


_streamlit_mock.columns = MagicMock(side_effect=_columns_mock)
sys.modules["streamlit"] = _streamlit_mock

# Mock polars (не доступен в core test env).
_polars_mock = ModuleType("polars")
_polars_mock.DataFrame = MagicMock()
sys.modules["polars"] = _polars_mock


def _page_path() -> Path:
    """Абсолютный путь к Streamlit-странице 90_Реестр_Маршрутов.py."""
    return (
        Path(__file__).resolve().parents[4]
        / "src"
        / "frontend"
        / "streamlit_app"
        / "pages"
        / "90_Реестр_Маршрутов.py"
    )


_load_counter = 0


def _build_streamlit_mock() -> ModuleType:
    """Build a fresh full-feature streamlit mock."""
    st = ModuleType("streamlit")
    for attr in [
        "set_page_config",
        "header",
        "metric",
        "divider",
        "subheader",
        "info",
        "warning",
        "caption",
        "tabs",
        "button",
        "rerun",
        "spinner",
        "dataframe",
        "json",
        "selectbox",
        "text_input",
        "multiselect",
        "expander",
    ]:
        setattr(st, attr, MagicMock())

    def _list_mock(spec):
        if isinstance(spec, int):
            n = spec
        elif hasattr(spec, "__len__"):
            n = len(spec)
        else:
            n = 1
        return [MagicMock() for _ in range(n)]

    st.columns = MagicMock(side_effect=_list_mock)
    st.tabs = MagicMock(side_effect=_list_mock)
    st.cache_data = _passthrough_decorator
    st.cache_resource = _passthrough_decorator
    return st


def _load_page_module() -> object:
    """Load page module by file path (Cyrillic name не импортируется напрямую).

    Each call returns a fresh module instance (to avoid state pollution
    when multiple tests run in sequence with different streamlit mocks).
    """
    global _load_counter
    _load_counter += 1
    module_name = f"_registry_explorer_page_{_load_counter}"

    # Always REPLACE sys.modules['streamlit'] with a fresh full mock
    # (previous tests may have replaced it with a minimal mock).
    sys.modules["streamlit"] = _build_streamlit_mock()

    spec = importlib.util.spec_from_file_location(module_name, _page_path())
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_page_file_exists() -> None:
    """Файл страницы существует на диске."""
    assert _page_path().exists(), f"Missing: {_page_path()}"


def test_page_uses_registry_explorer() -> None:
    """Page использует ``get_registry_explorer`` из core.registry_explorer."""
    source = _page_path().read_text(encoding="utf-8")
    assert "get_registry_explorer" in source
    assert "RouteEntry" in source
    assert "ConnectorEntry" in source


def test_page_has_seed_explorer_function() -> None:
    """``_seed_explorer`` функция определена."""
    tree = ast.parse(_page_path().read_text(encoding="utf-8"))
    func_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "_seed_explorer" in func_names


def test_page_calls_routes_inventory() -> None:
    """``_seed_explorer`` вызывает ``get_routes_inventory``."""
    source = _page_path().read_text(encoding="utf-8")
    assert "get_routes_inventory" in source


def test_seed_explorer_populates_registry() -> None:
    """``_seed_explorer`` корректно заполняет routes из inventory response."""
    from src.backend.core.registry_explorer import get_registry_explorer

    explorer = get_registry_explorer()
    explorer.clear()

    page_mod = _load_page_module()
    fake_client = MagicMock()
    fake_client.get_routes_inventory.return_value = {
        "routes": [
            {
                "route_id": "order-create",
                "source": "timer:60s",
                "owner": "team-x",
                "tags": ["prod"],
                "tenant_id": "t1",
                "timeout_seconds": 30.0,
            },
            {
                "route_id": "dadata-enrich",
                "source": "action:order-create",
                "owner": "team-x",
                "tags": ["prod"],
                "tenant_id": "t1",
                "timeout_seconds": 5.0,
            },
        ]
    }
    with patch.object(page_mod, "get_api_client", return_value=fake_client):
        page_mod._seed_explorer()

    assert (
        explorer.route_count() + explorer.connector_count() + explorer.action_count()
        == 2
    )
    assert explorer.find_route("order-create") is not None
    assert explorer.find_route("order-create").owner == "team-x"
    assert "prod" in explorer.find_route("order-create").tags


def test_seed_explorer_handles_empty_inventory() -> None:
    """``_seed_explorer`` обрабатывает пустой inventory response."""
    from src.backend.core.registry_explorer import get_registry_explorer

    explorer = get_registry_explorer()
    explorer.clear()

    page_mod = _load_page_module()
    fake_client = MagicMock()
    fake_client.get_routes_inventory.return_value = {"routes": []}
    with patch.object(page_mod, "get_api_client", return_value=fake_client):
        page_mod._seed_explorer()

    assert (
        explorer.route_count() + explorer.connector_count() + explorer.action_count()
        == 0
    )


def test_seed_explorer_handles_api_failure() -> None:
    """``_seed_explorer`` НЕ падает при ошибке API (graceful degradation)."""
    from src.backend.core.registry_explorer import get_registry_explorer

    explorer = get_registry_explorer()
    explorer.clear()

    page_mod = _load_page_module()
    fake_client = MagicMock()
    fake_client.get_routes_inventory.side_effect = RuntimeError("network")
    with patch.object(page_mod, "get_api_client", return_value=fake_client):
        page_mod._seed_explorer()

    # No crash, no routes added.
    assert (
        explorer.route_count() + explorer.connector_count() + explorer.action_count()
        == 0
    )


def test_registry_explorer_search_filter() -> None:
    """RegistryExplorer search/filter logic работает end-to-end."""
    from src.backend.core.registry_explorer import (
        ActionEntry,
        ConnectorEntry,
        RouteEntry,
        get_registry_explorer,
    )

    explorer = get_registry_explorer()
    explorer.clear()
    explorer.register_route(
        RouteEntry(id="r1", source="x", owner="team-x", tags=("prod",))
    )
    explorer.register_route(
        RouteEntry(id="r2", source="y", owner="team-y", tags=("dev",))
    )
    explorer.register_connector(
        ConnectorEntry(name="skb", category="external", auth="oauth2")
    )
    explorer.register_action(
        ActionEntry(name="orders.create", side_effect="write", owner="team-x")
    )

    team_x = explorer.list_routes_by_owner("team-x")
    assert len(team_x) == 1
    assert team_x[0].id == "r1"

    res = explorer.search_routes(owner="team-y", tag="dev")
    assert len(res) == 1
    assert res[0].id == "r2"

    assert len(explorer.list_connectors_by_category("external")) == 1
    assert explorer.summary() == {"routes": 2, "connectors": 1, "actions": 1}
