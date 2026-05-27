"""Table-компоненты для отображения данных с пагинацией."""

from __future__ import annotations

from typing import Any

import streamlit as st


def paginated_table(
    data: list[dict[str, Any]],
    *,
    page_size: int = 20,
    key: str | None = None,
) -> None:
    """Показать таблицу с пагинацией.

    Args:
        data: Список словарей для отображения.
        page_size: Количество строк на странице.
        key: Уникальный ключ для session_state.
    """
    if not data:
        st.info("Нет данных для отображения.")
        return

    total = len(data)
    page_key = key or "page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    total_pages = max(1, (total + page_size - 1) // page_size)
    page = st.session_state[page_key]

    start = page * page_size
    end = min(start + page_size, total)

    st.dataframe(data[start:end], use_container_width=True, hide_index=True)

    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("← Назад", key=f"{key}_prev" if key else None, disabled=page == 0):
            st.session_state[page_key] = page - 1
            st.rerun()
    with col_info:
        st.caption(f"Страница {page + 1} из {total_pages} ({total} записей)")
    with col_next:
        if st.button("Вперёд →", key=f"{key}_next" if key else None, disabled=page >= total_pages - 1):
            st.session_state[page_key] = page + 1
            st.rerun()


def render_metrics_table(metrics: dict[str, Any]) -> None:
    """Показать таблицу метрик в grid-стиле.

    Args:
        metrics: Словарь метрик (ключ → значение).
    """
    if not metrics:
        st.warning("Метрики недоступны.")
        return
    rows = [{"Метрика": k, "Значение": v} for k, v in metrics.items()]
    st.dataframe(rows, use_container_width=True, hide_index=True)
