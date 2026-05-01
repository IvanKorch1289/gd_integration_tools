"""Trace Logs — просмотр логов выполнения pipeline."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.entrypoints.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Logs", page_icon=":scroll:", layout="wide")
st.header("Trace Logs")

client = get_api_client()

# ──────────── Фильтры ────────────

col1, col2, col3 = st.columns(3)
route_filter = col1.text_input("Route ID")
corr_filter = col2.text_input("Correlation ID")
level_filter = col3.selectbox("Level", ["All", "Error", "Warning", "Info", "Debug"])

# ──────────── Загрузка логов ────────────

try:
    logs = client.get_trace_logs(limit=200)
    if not isinstance(logs, list):
        logs = []
except Exception:
    logs = []

if route_filter:
    logs = [
        log
        for log in logs
        if route_filter.lower() in str(log.get("route_id", "")).lower()
    ]

if corr_filter:
    logs = [log for log in logs if corr_filter in str(log.get("correlation_id", ""))]

if level_filter != "All":
    logs = [log for log in logs if log.get("level", "").lower() == level_filter.lower()]

# ──────────── Отображение ────────────

if logs:
    for log_entry in logs[:100]:
        level = log_entry.get("level", "info").lower()
        if level == "error":
            icon = ":red_circle:"
        elif level == "warning":
            icon = ":large_orange_circle:"
        else:
            icon = ":large_blue_circle:"

        route = log_entry.get("route_id", "—")
        proc = log_entry.get("processor", "—")
        ts = log_entry.get("timestamp", "")
        msg = log_entry.get("message", str(log_entry))

        st.markdown(f"{icon} **{route}** | `{proc}` | {ts}")
        st.text(msg)
        st.divider()

    st.caption(f"Показано {min(len(logs), 100)} из {len(logs)} записей")
else:
    st.info("Нет логов, соответствующих фильтру.")

if st.button("Обновить логи"):
    st.rerun()
