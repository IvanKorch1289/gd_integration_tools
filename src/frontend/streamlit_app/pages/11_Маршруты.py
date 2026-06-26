"""DSL Routes — просмотр и поиск маршрутов."""

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page(layout="wide",
    initial_sidebar_state="expanded",
)
st.header("DSL Маршруты")

client = get_api_client()

# ──────────── Фильтры ────────────

col1, col2 = st.columns([3, 1])
search = col1.text_input("Поиск по ID маршрута", placeholder="orders.*")
status_filter = col2.selectbox("Статус", ["All", "Enabled", "Disabled"])

# ──────────── Таблица ────────────

try:
    routes = client.get_routes()
    if not isinstance(routes, list):
        routes = []
except Exception:
    routes = []

if search:
    routes = [r for r in routes if search.lower() in str(r.get("route_id", "")).lower()]

if status_filter == "Enabled":
    routes = [r for r in routes if r.get("enabled", True)]
elif status_filter == "Disabled":
    routes = [r for r in routes if not r.get("enabled", True)]

if routes:
    import polars as pl

    df = pl.DataFrame(routes)
    display_cols = [
        c
        for c in [
            "route_id",
            "source",
            "enabled",
            "feature_flag",
            "protocol",
            "processors_count",
        ]
        if c in df.columns
    ]
    if display_cols:
        st.dataframe(df.select(display_cols), width='stretch')
    else:
        st.dataframe(df, width='stretch')
    st.caption(f"Всего: {len(routes)} маршрутов")
else:
    st.info("Нет маршрутов, соответствующих фильтру.")

related_pages_footer("11_Маршруты")
