# ruff: noqa: S101
"""Unit tests for shared/components.py (Sprint 43 W1).

Uses sys.modules mocking for streamlit + pandas (not installed in venv,
frontend-only deps). Tests verify call patterns, not actual rendering.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Mock streamlit + pandas BEFORE importing the component
_streamlit_mock = ModuleType("streamlit")
_streamlit_mock.set_page_config = MagicMock()
_streamlit_mock.columns = MagicMock(
    side_effect=lambda n: [MagicMock() for _ in range(n)]
)
_streamlit_mock.metric = MagicMock()
_streamlit_mock.dataframe = MagicMock()
sys.modules["streamlit"] = _streamlit_mock

# Mock pandas (only DataFrame is referenced via TYPE_CHECKING)
_pandas_mock = ModuleType("pandas")
_pandas_mock.DataFrame = MagicMock
sys.modules["pandas"] = _pandas_mock

# Now safe to import
from src.frontend.streamlit_app.shared.components import (  # noqa: E402
    dataframe_view,
    metric_row,
    setup_page,
)


@pytest.fixture(autouse=True)
def reset_mocks() -> None:
    """Reset mocks between tests."""
    _streamlit_mock.set_page_config.reset_mock()
    _streamlit_mock.metric.reset_mock()
    _streamlit_mock.dataframe.reset_mock()
    _streamlit_mock.columns.reset_mock()


# ── setup_page ──────────────────────────────────────────────────────


def test_setup_page_basic() -> None:
    """setup_page calls st.set_page_config with title + icon + defaults."""
    setup_page("My Page", "🚀")
    _streamlit_mock.set_page_config.assert_called_once_with(
        page_title="My Page",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def test_setup_page_centered_layout() -> None:
    """setup_page respects custom layout parameter."""
    setup_page("Compact", "📊", layout="centered")
    _streamlit_mock.set_page_config.assert_called_once_with(
        page_title="Compact",
        page_icon="📊",
        layout="centered",
        initial_sidebar_state="expanded",
    )


def test_setup_page_collapsed_sidebar() -> None:
    """setup_page respects custom initial_sidebar_state."""
    setup_page("No Sidebar", "⚙️", initial_sidebar_state="collapsed")
    _streamlit_mock.set_page_config.assert_called_once_with(
        page_title="No Sidebar",
        page_icon="⚙️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )


# ── metric_row ──────────────────────────────────────────────────────


def test_metric_row_three_columns() -> None:
    """metric_row creates 3 columns + 3 st.metric calls."""
    metric_row([("Users", 100), ("Sessions", 50), ("Errors", 2)])
    _streamlit_mock.columns.assert_called_once_with(3)
    assert _streamlit_mock.metric.call_count == 3
    _streamlit_mock.metric.assert_any_call("Users", 100)
    _streamlit_mock.metric.assert_any_call("Sessions", 50)
    _streamlit_mock.metric.assert_any_call("Errors", 2)


def test_metric_row_with_delta() -> None:
    """metric_row passes delta when 3-tuple provided."""
    metric_row([("Revenue", 1000, "+10%")])
    _streamlit_mock.metric.assert_called_once_with("Revenue", 1000, delta="+10%")


def test_metric_row_empty() -> None:
    """metric_row with empty list is a no-op."""
    metric_row([])
    _streamlit_mock.columns.assert_not_called()
    _streamlit_mock.metric.assert_not_called()


def test_metric_row_single() -> None:
    """metric_row with single metric works."""
    metric_row([("Single", 42)])
    _streamlit_mock.columns.assert_called_once_with(1)
    _streamlit_mock.metric.assert_called_once_with("Single", 42)


# ── dataframe_view ──────────────────────────────────────────────────


def test_dataframe_view_default_use_container_width() -> None:
    """dataframe_view auto-sets use_container_width=True by default."""
    df = MagicMock(name="DataFrame")
    dataframe_view(df)
    _streamlit_mock.dataframe.assert_called_once_with(df, use_container_width=True)


def test_dataframe_view_respects_explicit_kwarg() -> None:
    """dataframe_view allows override of use_container_width."""
    df = MagicMock(name="DataFrame")
    dataframe_view(df, use_container_width=False, height=300)
    _streamlit_mock.dataframe.assert_called_once_with(
        df, use_container_width=False, height=300
    )


def test_dataframe_view_forwards_extra_kwargs() -> None:
    """dataframe_view forwards all kwargs to st.dataframe."""
    df = MagicMock(name="DataFrame")
    dataframe_view(df, hide_index=True, column_config={"a": "A"})
    call_kwargs = _streamlit_mock.dataframe.call_args.kwargs
    assert call_kwargs["hide_index"] is True
    assert call_kwargs["column_config"] == {"a": "A"}
    assert call_kwargs["use_container_width"] is True
