"""Feedback-компоненты для отображения сообщений."""

from __future__ import annotations

import streamlit as st


def success_msg(message: str, *, key: str | None = None) -> None:
    """Показать success-сообщение."""
    if key:
        st.success(message, key=key)  # type: ignore[call-arg]  # R2.MYPY: streamlit st.success stub has no `key` param
    else:
        st.success(message)


def error_msg(message: str, *, key: str | None = None) -> None:
    """Показать error-сообщение."""
    if key:
        st.error(message, key=key)  # type: ignore[call-arg]  # R2.MYPY: streamlit st.error stub
    else:
        st.error(message)


def warning_msg(message: str, *, key: str | None = None) -> None:
    """Показать warning-сообщение."""
    if key:
        st.warning(message, key=key)  # type: ignore[call-arg]  # R2.MYPY: streamlit st.warning stub
    else:
        st.warning(message)


def info_msg(message: str, *, key: str | None = None) -> None:
    """Показать info-сообщение."""
    if key:
        st.info(message, key=key)  # type: ignore[call-arg]  # R2.MYPY: streamlit st.info stub
    else:
        st.info(message)
