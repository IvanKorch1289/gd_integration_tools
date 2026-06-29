"""Badge-компоненты для отображения статусов."""

from __future__ import annotations

import streamlit as st


def status_badge(status: str | bool, label: str | None = None) -> None:
    """Показать badge статуса с цветовой индикацией.

    Args:
        status: Статус (True/False для ok/fail, или строка
'ok'/'fail'/'pending'/'retry').
        label: Опциональный текст (по умолчанию — status).
    """
    text = label or str(status)
    if status is True or status == "ok":
        st.success(f"✓ {text}")
    elif status is False or status in ("fail", "error"):
        st.error(f"✗ {text}")
    elif status == "pending":
        st.warning(f"⏳ {text}")
    elif status == "retry":
        st.info(f"🔁 {text}")
    else:
        st.caption(text)


def health_badge(name: str, healthy: bool) -> None:
    """Показать badge здоровья компонента.

    Args:
        name: Имя компонента.
        healthy: True если здоров.
    """
    if healthy:
        st.success(f"✓ {name}")
    else:
        st.error(f"✗ {name}")
