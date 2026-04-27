"""DSL Routes — просмотр и поиск маршрутов."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.entrypoints.streamlit_app.api_client import get_api_client

st.set_page_config(
    page_title="Routes", page_icon=":twisted_rightwards_arrows:", layout="wide"
)
st.header("DSL Routes")

client = get_api_client()

# ──────────── Фильтры ────────────

col1, col2 = st.columns([3, 1])
search = col1.text_input("Поиск по route ID", placeholder="orders.*")
status_filter = col2.selectbox("Status", ["All", "Enabled", "Disabled"])

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
        st.dataframe(df.select(display_cols), use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)
    st.caption(f"Всего: {len(routes)} маршрутов")
else:
    st.info("Нет маршрутов, соответствующих фильтру.")
