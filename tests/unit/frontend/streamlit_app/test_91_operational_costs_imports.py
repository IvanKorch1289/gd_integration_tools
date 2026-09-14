"""S175 W2: tests для 91_Операционные_Затраты.py (Operational Costs page).

Проверяем:
- Файл существует.
- Использует ``core.cost_attribution`` (CostAttribution, CostRecord).
- ``@track_cost`` decorator упоминается в help.
- ``_get_registry`` + ``_format_currency`` хелперы определены.
- Регистрация записи через registry.record → отображается в page.
- Lazy ``_get_registry()`` для testability.
- CostReport.to_dict() используется для export tab.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch


# Mock streamlit (full surface) BEFORE any imports.
_streamlit_mock = ModuleType("streamlit")
for attr in [
    "set_page_config", "header", "metric", "divider", "subheader",
    "info", "warning", "caption", "tabs", "button",
    "rerun", "spinner", "dataframe", "json", "selectbox",
    "text_input", "multiselect", "expander", "download_button",
    "subheader", "bar_chart", "stop",
]:
    setattr(_streamlit_mock, attr, MagicMock())


def _list_mock(spec):
    if isinstance(spec, int):
        n = spec
    elif hasattr(spec, "__len__"):
        n = len(spec)
    else:
        n = 1
    return [MagicMock() for _ in range(n)]


_streamlit_mock.tabs = MagicMock(side_effect=_list_mock)
_streamlit_mock.columns = MagicMock(side_effect=_list_mock)


def _passthrough_decorator(*_args, **_kwargs):
    def _decorator(fn):
        return fn
    return _decorator


_streamlit_mock.cache_data = _passthrough_decorator
_streamlit_mock.cache_resource = _passthrough_decorator
sys.modules["streamlit"] = _streamlit_mock

# Mock polars.
_polars_mock = ModuleType("polars")
_polars_mock.DataFrame = MagicMock()
sys.modules["polars"] = _polars_mock


def _page_path() -> Path:
    """Абсолютный путь к Streamlit-странице 91_Операционные_Затраты.py."""
    return (
        Path(__file__).resolve().parents[4]
        / "src"
        / "frontend"
        / "streamlit_app"
        / "pages"
        / "91_Операционные_Затраты.py"
    )


def _read_source() -> str:
    return _page_path().read_text(encoding="utf-8")


def _parse_ast() -> object:
    import ast
    return ast.parse(_read_source())


_load_counter = 0


def _build_streamlit_mock() -> ModuleType:
    """Fresh full-feature streamlit mock (для test isolation)."""
    st = ModuleType("streamlit")
    for attr in [
        "set_page_config", "header", "metric", "divider", "subheader",
        "info", "warning", "caption", "tabs", "button",
        "rerun", "spinner", "dataframe", "json", "selectbox",
        "text_input", "multiselect", "expander", "download_button",
        "subheader", "bar_chart", "stop",
    ]:
        setattr(st, attr, MagicMock())
    st.tabs = MagicMock(side_effect=_list_mock)
    st.columns = MagicMock(side_effect=_list_mock)
    st.cache_data = _passthrough_decorator
    st.cache_resource = _passthrough_decorator
    return st


def _load_page_module() -> object:
    """Load page module via spec_from_file_location (Cyrillic name)."""
    global _load_counter
    _load_counter += 1
    module_name = f"_operational_costs_page_{_load_counter}"
    sys.modules["streamlit"] = _build_streamlit_mock()
    spec = importlib.util.spec_from_file_location(
        module_name, _page_path()
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_page_file_exists() -> None:
    """Файл страницы существует на диске."""
    assert _page_path().exists(), f"Missing: {_page_path()}"


def test_page_uses_cost_attribution() -> None:
    """Page использует core.cost_attribution (CostAttribution, CostRecord, get_cost_registry)."""
    source = _read_source()
    assert "CostAttribution" in source
    assert "CostRecord" in source
    assert "get_cost_registry" in source


def test_page_mentions_track_cost_decorator() -> None:
    """Page help ссылается на @track_cost decorator."""
    source = _read_source()
    assert "@track_cost" in source
    assert "ResourceType" in source


def test_page_has_required_functions() -> None:
    """_get_registry, _format_currency, related_pages_footer call."""
    source = _read_source()
    assert "_get_registry" in source
    assert "_format_currency" in source
    assert "related_pages_footer" in source


def test_get_registry_returns_singleton() -> None:
    """``_get_registry()`` returns singleton."""
    page_mod = _load_page_module()
    r1 = page_mod._get_registry()
    r2 = page_mod._get_registry()
    assert r1 is r2


def test_format_currency_basic() -> None:
    """``_format_currency`` корректно форматирует разные magnitudes."""
    page_mod = _load_page_module()
    # Micro (<0.01) → 6 decimals.
    assert "0.000100" in page_mod._format_currency(0.0001)
    # Mid (<1) → 4 decimals.
    assert "0.1000" in page_mod._format_currency(0.1)
    # Normal → 2 decimals.
    assert "10.00" in page_mod._format_currency(10.0)


def test_cost_record_appears_in_page() -> None:
    """``CostRecord`` registered → отображается в page registry list."""
    from src.backend.core.cost_attribution import ResourceType

    registry = get_cost_registry_via_page()
    registry.clear()
    registry.record(
        tenant_id="t1",
        route_id="r1",
        resource_type=ResourceType.LLM_TOKENS,
        units=1000,
        cost_usd=0.10,
        agent="alice",
    )
    records = registry.list_records()
    assert len(records) == 1
    assert records[0].cost_usd == 0.10
    assert records[0].tenant_id == "t1"


def get_cost_registry_via_page() -> object:
    """Use the page's lazy getter (через dynamic import)."""
    page_mod = _load_page_module()
    return page_mod._get_registry()


def test_cost_report_export() -> None:
    """CostReport to_dict() содержит summary + by_tenant + records."""
    from src.backend.core.cost_attribution import (
        CostReport,
        ResourceType,
    )

    records = [
        # Mock records.
        MagicMock(cost_usd=0.05, units=100, resource_type=ResourceType.LLM_TOKENS),
        MagicMock(cost_usd=0.10, units=200, resource_type=ResourceType.LLM_TOKENS),
    ]
    rep = CostReport(timestamp=123.0, records=records)
    d = rep.to_dict()
    assert d["timestamp"] == 123.0
    assert "by_tenant" in d
    assert "by_resource" in d
    assert "by_agent" in d


def test_aggregation_by_tenant_via_registry() -> None:
    """Записи группируются по tenant_id (by_tenant)."""
    from src.backend.core.cost_attribution import ResourceType

    registry = get_cost_registry_via_page()
    registry.clear()
    registry.record(
        tenant_id="t1", route_id="r1", resource_type=ResourceType.LLM_TOKENS,
        units=100, cost_usd=0.01,
    )
    registry.record(
        tenant_id="t1", route_id="r2", resource_type=ResourceType.HTTP_REQUESTS,
        units=1, cost_usd=0.001,
    )
    registry.record(
        tenant_id="t2", route_id="r1", resource_type=ResourceType.LLM_TOKENS,
        units=200, cost_usd=0.02,
    )

    records = registry.list_records()
    by_tenant: dict[str, float] = {}
    for r in records:
        by_tenant[r.tenant_id] = by_tenant.get(r.tenant_id, 0.0) + r.cost_usd
    assert by_tenant["t1"] == 0.011
    assert by_tenant["t2"] == 0.02
