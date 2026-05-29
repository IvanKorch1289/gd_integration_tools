"""Хуки для управления состоянием Streamlit."""

from __future__ import annotations

from typing import Any

import streamlit as st


def init_state(**kwargs: Any) -> None:
    """Инициализировать ключи session_state если их ещё нет.

    Args:
        **kwargs: Пары key=value для инициализации.
    """
    for key, value in kwargs.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_state(key: str, default: Any = None) -> Any:
    """Получить значение из session_state с дефолтом.

    Args:
        key: Ключ.
        default: Значение по умолчанию.

    Returns:
        Значение из session_state или default.
    """
    return st.session_state.get(key, default)


def clear_state(*keys: str) -> None:
    """Очистить указанные ключи из session_state.

    Args:
        *keys: Ключи для очистки.
    """
    for key in keys:
        if key in st.session_state:
            del st.session_state[key]
