"""Streamlit-страница 74 — RAG Cache Dashboard (К4 MVP, Шаг 7).

4 таб'а: L1 / L2 / L3 / Invalidation. Live hit-rate, кнопка flush,
events-table. При недоступном backend'е страница рендерит пустой state
без падения.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_client_k4 import K4APIClient

st.set_page_config(page_title="RAG Cache Dashboard", page_icon="🗂️", layout="wide")
st.title("🗂️ RAG Cache Dashboard")

client = K4APIClient()
stats = client.get_rag_cache_stats()
counters = stats.get("counters", {"hits": {}, "misses": {}})
enabled = stats.get("enabled", {})

tab_l1, tab_l2, tab_l3, tab_inv = st.tabs(
    ["L1 Exact", "L2 Semantic", "L3 Retrieval", "Invalidation"]
)


def _render_tier(tier_name: str, tier_key: str) -> None:
    hits = int(counters.get("hits", {}).get(tier_key, 0))
    misses = int(counters.get("misses", {}).get(tier_key, 0))
    total = hits + misses
    hit_rate = (hits / total * 100) if total else 0.0
    is_enabled = bool(enabled.get(tier_key, False))

    col_state, col_hits, col_misses, col_rate = st.columns(4)
    col_state.metric("Состояние", "ON" if is_enabled else "OFF")
    col_hits.metric("Hits", hits)
    col_misses.metric("Misses", misses)
    col_rate.metric("Hit-rate", f"{hit_rate:.1f}%")

    if st.button(f"Flush {tier_name}", key=f"flush-{tier_key}"):
        result = client.flush_rag_cache_tier(tier_key)
        st.success(f"Flush результат: {result}")


with tab_l1:
    _render_tier("L1", "l1")

with tab_l2:
    _render_tier("L2", "l2")

with tab_l3:
    _render_tier("L3", "l3")

with tab_inv:
    st.subheader("Последние invalidate-события")
    events = client.get_rag_invalidation_events(limit=100)
    if events:
        st.dataframe(events, use_container_width=True)
    else:
        st.info("Событий пока нет.")
    if st.button("Flush all tiers", key="flush-all"):
        st.warning(client.flush_rag_cache_tier(None))
