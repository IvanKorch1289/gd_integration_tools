"""Sprint 14 K3 W1 — Processor Catalog Search UI.

Live-поиск по DSL-процессорам через rapidfuzz (latency ≤ 200ms).
Использует backend endpoint ``GET /api/v1/dsl/processors/search``.

Защищено feature_flag ``processor_catalog_search_ui`` (default-OFF).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page
from src.frontend.streamlit_app.shared.filters import text_search  # S44 W2 (TD-008)

setup_page("Processor Catalog", "🔍")
st.title("🔍 Processor Catalog Search")
st.caption("Fuzzy search across DSL processors (rapidfuzz).")

client = get_api_client()


with st.sidebar:
    st.header("Filters")
    query = text_search("Search query", placeholder="например: 'split aggregate'")
    namespace = st.selectbox(
        "Namespace",
        options=[
            "",
            "core",
            "control_flow",
            "routing",
            "transformation",
            "resilience",
            "flow_control",
            "idempotency",
            "sequencing",
            "components",
            "converters",
            "patterns",
            "scraping",
            "ai",
            "rpa",
            "web",
            "external",
            "integration",
            "export",
            "dq_check",
        ],
        index=0,
    )
    limit = st.slider("Limit", min_value=5, max_value=100, value=25, step=5)


payload = client.get_processor_catalog(
    query=query, namespace=namespace or None, limit=limit
)

if "error" in payload:
    st.error(f"Search failed: {payload['error']}")
elif payload.get("total", 0) == 0:
    st.info("Нет процессоров для текущего фильтра.")
else:
    st.success(f"Найдено: **{payload['total']}** процессоров.")
    for item in payload.get("items", []):
        with st.container(border=True):
            cols = st.columns([3, 1])
            with cols[0]:
                st.markdown(f"### `{item['name']}`")
                st.caption(f"Namespace: `{item.get('category', '—')}`")
                if item.get("description"):
                    st.write(item["description"])
            with cols[1]:
                st.metric("Match score", item.get("score", 0))
