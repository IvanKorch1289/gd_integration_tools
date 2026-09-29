"""Unit tests for shared/components.py (Sprint 43 W1).

Uses sys.modules mocking for streamlit + pandas (not installed in venv,
frontend-only deps). Tests verify call patterns, not actual rendering.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_COMPONENTS_MODULE = "src.frontend.streamlit_app.shared.components"
_STUBBED_MODULES = ("streamlit", "pandas")

# (модуль components, mock-модуль streamlit)
ComponentsEnv = tuple[ModuleType, ModuleType]


def _build_stubs() -> ComponentsEnv:
    """Собрать минимальные заглушки streamlit + pandas (frontend-only deps)."""
    st = ModuleType("streamlit")
    st.set_page_config = MagicMock()
    st.columns = MagicMock(side_effect=lambda n: [MagicMock() for _ in range(n)])
    st.metric = MagicMock()
    st.dataframe = MagicMock()
    # pandas используется только в аннотациях (TYPE_CHECKING).
    pd = ModuleType("pandas")
    pd.DataFrame = MagicMock
    return st, pd


@pytest.fixture(scope="module")
def components_env() -> Iterator[ComponentsEnv]:
    """Подменить streamlit/pandas ТОЛЬКО на время тестов этого модуля.

    Раньше заглушки ставились на уровне модуля, то есть на этапе СБОРКИ
    (collection), и никогда не восстанавливались. Поэтому на весь остальной
    процесс ``streamlit`` оставался модулем из 4 атрибутов, а ``pandas`` —
    модулем с единственным ``DataFrame``. Любой тест, выполнявшийся после,
    получал эти mock-объекты: например ``api_clients/cached.py`` падал на
    ``@st.cache_data(...)`` с
    ``AttributeError: module 'streamlit' has no attribute 'cache_data'``.

    Измерено на этом дереве: кластер ``tests/unit/frontend`` даёт 21 падение
    с этим файлом и 12 без него — то есть ровно 9 падений вызваны утечкой
    заглушек, а не реальными дефектами.

    Yields:
        Кортеж (модуль components, mock-модуль streamlit).
    """
    saved = {name: sys.modules.get(name) for name in _STUBBED_MODULES}
    st, pd = _build_stubs()
    sys.modules["streamlit"] = st
    sys.modules["pandas"] = pd
    # Модуль мог быть импортирован ранее — против настоящего streamlit.
    sys.modules.pop(_COMPONENTS_MODULE, None)
    try:
        yield importlib.import_module(_COMPONENTS_MODULE), st
    finally:
        sys.modules.pop(_COMPONENTS_MODULE, None)
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


@pytest.fixture(autouse=True)
def reset_mocks(components_env: ComponentsEnv) -> None:
    """Reset mocks between tests."""
    _, st = components_env
    st.set_page_config.reset_mock()
    st.metric.reset_mock()
    st.dataframe.reset_mock()
    st.columns.reset_mock()


# ── setup_page ──────────────────────────────────────────────────────


def test_setup_page_basic(components_env: ComponentsEnv) -> None:
    """setup_page calls st.set_page_config with title + icon + defaults."""
    components, st = components_env
    components.setup_page("My Page", "🚀")
    st.set_page_config.assert_called_once_with(
        page_title="My Page",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def test_setup_page_centered_layout(components_env: ComponentsEnv) -> None:
    """setup_page respects custom layout parameter."""
    components, st = components_env
    components.setup_page("Compact", "📊", layout="centered")
    st.set_page_config.assert_called_once_with(
        page_title="Compact",
        page_icon="📊",
        layout="centered",
        initial_sidebar_state="expanded",
    )


def test_setup_page_collapsed_sidebar(components_env: ComponentsEnv) -> None:
    """setup_page respects custom initial_sidebar_state."""
    components, st = components_env
    components.setup_page("No Sidebar", "⚙️", initial_sidebar_state="collapsed")
    st.set_page_config.assert_called_once_with(
        page_title="No Sidebar",
        page_icon="⚙️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )


# ── metric_row ──────────────────────────────────────────────────────


def test_metric_row_three_columns(components_env: ComponentsEnv) -> None:
    """metric_row creates 3 columns + 3 st.metric calls."""
    components, st = components_env
    components.metric_row([("Users", 100), ("Sessions", 50), ("Errors", 2)])
    st.columns.assert_called_once_with(3)
    assert st.metric.call_count == 3
    st.metric.assert_any_call("Users", 100)
    st.metric.assert_any_call("Sessions", 50)
    st.metric.assert_any_call("Errors", 2)


def test_metric_row_with_delta(components_env: ComponentsEnv) -> None:
    """metric_row passes delta when 3-tuple provided."""
    components, st = components_env
    components.metric_row([("Revenue", 1000, "+10%")])
    st.metric.assert_called_once_with("Revenue", 1000, delta="+10%")


def test_metric_row_empty(components_env: ComponentsEnv) -> None:
    """metric_row with empty list is a no-op."""
    components, st = components_env
    components.metric_row([])
    st.columns.assert_not_called()
    st.metric.assert_not_called()


def test_metric_row_single(components_env: ComponentsEnv) -> None:
    """metric_row with single metric works."""
    components, st = components_env
    components.metric_row([("Single", 42)])
    st.columns.assert_called_once_with(1)
    st.metric.assert_called_once_with("Single", 42)


# ── dataframe_view ──────────────────────────────────────────────────


def test_dataframe_view_default_width_stretch(components_env: ComponentsEnv) -> None:
    """dataframe_view auto-sets width='stretch' by default."""
    components, st = components_env
    df = MagicMock(name="DataFrame")
    components.dataframe_view(df)
    st.dataframe.assert_called_once_with(df, width="stretch")


def test_dataframe_view_respects_explicit_width(components_env: ComponentsEnv) -> None:
    """dataframe_view allows override of width."""
    components, st = components_env
    df = MagicMock(name="DataFrame")
    components.dataframe_view(df, width="content", height=300)
    st.dataframe.assert_called_once_with(df, width="content", height=300)


def test_dataframe_view_forwards_extra_kwargs(components_env: ComponentsEnv) -> None:
    """dataframe_view forwards all kwargs to st.dataframe."""
    components, st = components_env
    df = MagicMock(name="DataFrame")
    components.dataframe_view(df, hide_index=True, column_config={"a": "A"})
    call_kwargs = st.dataframe.call_args.kwargs
    assert call_kwargs["hide_index"] is True
    assert call_kwargs["column_config"] == {"a": "A"}
    assert call_kwargs["width"] == "stretch"
