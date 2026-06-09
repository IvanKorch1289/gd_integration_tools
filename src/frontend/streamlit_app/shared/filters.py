"""Reusable filter components for Streamlit pages (Sprint 43 W2).

TD-008 Group 3 (P2 dup group): filter+search boilerplate pattern repeated
across 48 / 69 pages (audit S42 W3, 2026-06-09):

- text_search: st.text_input wrapper для search inputs (7 pages).
- multiselect_filter: st.multiselect wrapper с type-safe defaults (9 pages).
- date_range_filter: pair of st.date_input для date range (4 pages).
- selectbox_filter: st.selectbox wrapper с default handling (38 pages).

**Эти helpers — light wrapper around streamlit primitives.** Они
**не** пытаются enforce единый UX (filter chips, persisted state, и
т.д.) — это намеренно: каждая страница имеет свой context. Helpers
standardize:
- Labels (Russian-first per CLAUDE.md)
- Type hints (return types explicit)
- Optional `key` param для multi-filter pages
- `default` semantics consistent across helpers

Usage:
    from src.frontend.streamlit_app.shared.filters import (
        text_search, multiselect_filter, date_range_filter,
    )

    query = text_search("Поиск workflow")
    selected = multiselect_filter("Типы", options=types, default=types)
    from_date, to_date = date_range_filter("Период")
"""

from __future__ import annotations

from datetime import date
from typing import TypeVar

import streamlit as st

__all__ = (
    "text_search",
    "multiselect_filter",
    "date_range_filter",
    "selectbox_filter",
    "slider_filter",
)

T = TypeVar("T")


def text_search(
    label: str,
    *,
    placeholder: str = "",
    key: str | None = None,
) -> str:
    """st.text_input wrapper для search/filter queries.

    Args:
        label: Filter label (Russian-first).
        placeholder: Optional placeholder text.
        key: Streamlit widget key (для уникальности при multi-filter).

    Returns:
        Trimmed query string (empty если ничего не введено).
    """
    raw = st.text_input(
        label,
        value="",
        placeholder=placeholder,
        key=key,
    )
    return raw.strip() if raw else ""


def multiselect_filter(
    label: str,
    *,
    options: list[T],
    default: list[T] | None = None,
    key: str | None = None,
) -> list[T]:
    """st.multiselect wrapper с type-safe defaults.

    Args:
        label: Filter label.
        options: Available options (any type).
        default: Initially selected options (default: empty).
        key: Streamlit widget key.

    Returns:
        Selected options (subset of `options`).
    """
    return st.multiselect(
        label,
        options=options,
        default=default if default is not None else [],
        key=key,
    )


def date_range_filter(
    label: str,
    *,
    key_prefix: str | None = None,
) -> tuple[date | None, date | None]:
    """Pair of st.date_input для from/to range.

    Args:
        label: Section label (e.g. "Период").
        key_prefix: Optional prefix для widget keys (default: label).

    Returns:
        (from_date, to_date) tuple. Either may be None.
    """
    prefix = key_prefix or label
    cols = st.columns(2)  # type: ignore[union-attr]
    with cols[0]:  # type: ignore[union-attr]
        from_date = st.date_input(
            f"{label} — с",
            value=None,
            key=f"{prefix}_from",
        )
    with cols[1]:  # type: ignore[union-attr]
        to_date = st.date_input(
            f"{label} — по",
            value=None,
            key=f"{prefix}_to",
        )
    return (from_date if isinstance(from_date, date) else None,
            to_date if isinstance(to_date, date) else None)


def selectbox_filter(
    label: str,
    *,
    options: list[T],
    default: T | None = None,
    key: str | None = None,
) -> T | None:
    """st.selectbox wrapper с default handling.

    Args:
        label: Filter label.
        options: Available options.
        default: Initially selected option (default: first item).
        key: Streamlit widget key.

    Returns:
        Selected option or None if options is empty.
    """
    if not options:
        return None
    index = 0
    if default is not None and default in options:
        index = list(options).index(default)
    return st.selectbox(
        label,
        options=options,
        index=index,
        key=key,
    )


def slider_filter(
    label: str,
    *,
    min_value: int,
    max_value: int,
    step: int = 1,
    default: int | None = None,
    key: str | None = None,
) -> int:
    """st.slider wrapper с type-safe defaults.

    Args:
        label: Filter label.
        min_value: Minimum value.
        max_value: Maximum value.
        step: Slider step (default: 1).
        default: Initial value (default: min_value).
        key: Streamlit widget key.

    Returns:
        Selected integer value.
    """
    return st.slider(
        label,
        min_value=min_value,
        max_value=max_value,
        step=step,
        value=default if default is not None else min_value,
        key=key,
    )
