"""Общие UI components и helpers для Streamlit pages (Sprint 43 W1).

Consolidates patterns repeated across 66+ pages (per Sprint 42 W3 audit):
- setup_page(): replaces 5-line st.set_page_config boilerplate
- metric_row(): replaces 3-column st.metric pattern (36 pages)
- dataframe_view(): replaces st.dataframe with consistent styling

Usage:
    from src.frontend.streamlit_app.shared.components import (
        setup_page, metric_row, dataframe_view,
    )

    setup_page("My Page", "🚀")
    metric_row([("Label 1", value1), ("Label 2", value2)])
    dataframe_view(df)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import streamlit as st

if TYPE_CHECKING:
    import pandas as pd

__all__ = ("setup_page", "metric_row", "dataframe_view")


def setup_page(
    title: str | None = None,
    icon: str | None = None,
    *,
    layout: str = "wide",
    initial_sidebar_state: str = "expanded",
    auto_resolve: bool = True,
) -> None:
    """Standard page setup: replaces 5-line st.set_page_config boilerplate.

    S171 (S2 optimization): If title/icon not provided, auto-resolves from
    page_registry.PAGE_METADATA by inspecting caller filename.

    Replaces this pattern (used in 66+ pages):
        st.set_page_config(
            page_title="...",
            page_icon="...",
            layout="wide",
            initial_sidebar_state="expanded",
        )

    Args:
        title: Page title (shown in browser tab + Streamlit sidebar).
               If None and auto_resolve=True, looked up from registry.
        icon: Material icon / emoji / URL. If None and auto_resolve=True,
              looked up from registry.
        layout: "centered" or "wide" (default: "wide").
        initial_sidebar_state: "auto" | "expanded" | "collapsed".
        auto_resolve: If True, use page_registry to fill missing args.
    """
    if auto_resolve and (title is None or icon is None):
        from src.frontend.streamlit_app.shared.page_registry import get_page_metadata
        import inspect
        caller_file = inspect.stack()[1].filename
        # Extract page filename without .py
        page_name = Path(caller_file).stem
        meta = get_page_metadata(page_name)
        if meta:
            if title is None:
                title = meta["title"]
            if icon is None:
                icon = meta["icon"]

    # Fallback defaults
    if title is None:
        title = "GD Integration Tools"
    if icon is None:
        icon = ":material/extension:"

    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout=layout,
        initial_sidebar_state=initial_sidebar_state,
    )


def metric_row(metrics: list[tuple[str, Any]]) -> None:
    """Render a row of st.metric widgets in equal-width columns.

    Replaces this pattern (used in 36+ pages):
        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Label 1", value1)
        with col2: st.metric("Label 2", value2)
        with col3: st.metric("Label 3", value3)

    Args:
        metrics: List of (label, value) tuples. Also accepts 2-tuples
            with optional delta as 3rd element.
    """
    if not metrics:
        return
    cols = st.columns(len(metrics))
    for col, item in zip(cols, metrics, strict=True):
        label = item[0]
        value = item[1]
        delta = item[2] if len(item) > 2 else None
        with col:
            if delta is not None:
                st.metric(label, value, delta=delta)
            else:
                st.metric(label, value)


def dataframe_view(df: pd.DataFrame, **kwargs: Any) -> None:
    """Render a DataFrame with consistent styling (width='stretch').

    Replaces this pattern (used in 30+ pages):
        st.dataframe(df, width='stretch')

    Args:
        df: pandas DataFrame to display.
        **kwargs: Forwarded to st.dataframe.
    """
    kwargs.setdefault("width", "stretch")
    st.dataframe(df, **kwargs)
