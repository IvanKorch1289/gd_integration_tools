"""Streamlit page Adaptive RAG dashboard (Sprint 11 K5 W1).

Показывает распределение выбора стратегий ``dense|hybrid|hyde|multi_query``
по типам запросов. Источник — ``/admin/rag/strategy-stats``.
"""

from __future__ import annotations

import streamlit as st

try:
    from src.frontend.streamlit_app.api_clients import APIClient
except ImportError:  # pragma: no cover
    APIClient = None  # type: ignore[misc]

st.set_page_config(page_title="Adaptive RAG", page_icon="🧠", layout="wide")
st.title("🧠 Adaptive RAG Strategy Dashboard")
st.caption(
    "Распределение стратегий retrieval (`dense`/`hybrid`/`hyde`/`multi_query`). "
    "Feature-flag: `adaptive_rag_strategy`."
)


def _fetch() -> dict | None:
    if APIClient is None:
        st.error("APIClient недоступен.")
        return None
    try:
        return APIClient().get("/admin/rag/strategy-stats")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить stats: {exc}")
        return None


def main() -> None:
    data = _fetch()
    if not data:
        return

    stats = data.get("strategies") or {}
    total = data.get("total") or 0
    feature_on = data.get("feature_enabled", False)

    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("Всего запросов", total)
        st.metric("Стратегий активно", len([k for k, v in stats.items() if v > 0]))
        st.write(f"Feature-flag: **{'ON' if feature_on else 'OFF'}**")

    with col2:
        if total == 0:
            st.info("Пока нет данных — селектор ещё не вызывался.")
        else:
            st.bar_chart(stats, height=300)

    st.markdown("---")
    st.subheader("Подробности по стратегиям")
    for strategy, count in stats.items():
        ratio = count / total if total else 0.0
        st.write(f"- `{strategy}` — **{count}** ({ratio:.1%})")


main()
