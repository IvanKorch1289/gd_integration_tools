"""Cache Admin — объединение Cache Explorer и RAG Cache Dashboard.

Вкладки:
* Redis Cache — просмотр и инвалидация ключей.
* RAG Cache — L1/L2/L3 tiers, hit-rate, flush.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import K4APIClient, get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page('Cache Admin', ':package:')
st.header(":package: Cache Admin")

tab_redis, tab_rag = st.tabs(["Redis Cache", "RAG Cache"])

with tab_redis:
    st.subheader("Cache Explorer")
    client = get_api_client()

    pattern = st.text_input(
        "Pattern поиска ключей",
        value="*",
        help="Glob-паттерн Redis (напр., `user:*`)",
        key="redis_pattern",
    )

    try:
        keys = client._request(
            "GET", "/api/v1/admin/cache/keys", params={"pattern": pattern, "limit": 200}
        )
        if not isinstance(keys, list):
            keys = []
    except Exception as exc:  # noqa: BLE001
        keys = []
        st.error(f"Не удалось получить ключи: {exc}")

    st.caption(f"Найдено: {len(keys)}")

    for key in keys[:100]:
        with st.expander(key):
            try:
                data = client._request("GET", f"/api/v1/admin/cache/{key}")
                st.json(data)
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
            if st.button("Удалить", key=f"del_{key}"):
                try:
                    client._request("DELETE", f"/api/v1/admin/cache/{key}")
                    st.success("Удалено")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    st.divider()
    st.subheader("Массовая инвалидация")
    invalidate_pattern = st.text_input(
        "Pattern для инвалидации", value="", key="inv_pat"
    )
    if st.button("Invalidate") and invalidate_pattern:
        try:
            resp = client._request(
                "POST",
                "/api/v1/admin/cache/invalidate",
                params={"pattern": invalidate_pattern},
            )
            st.success(f"Удалено: {resp}")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

with tab_rag:
    st.subheader("RAG Cache Dashboard")
    client_k4 = K4APIClient()
    stats = client_k4.get_rag_cache_stats()
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
            result = client_k4.flush_rag_cache_tier(tier_key)
            st.success(f"Flush результат: {result}")

    with tab_l1:
        _render_tier("L1", "l1")

    with tab_l2:
        _render_tier("L2", "l2")

    with tab_l3:
        _render_tier("L3", "l3")

    with tab_inv:
        st.subheader("Последние invalidate-события")
        events = client_k4.get_rag_invalidation_events(limit=100)
        if events:
            st.dataframe(events, use_container_width=True)
        else:
            st.info("Событий пока нет.")
        if st.button("Flush all tiers", key="flush-all"):
            st.warning(client_k4.flush_rag_cache_tier(None))
