"""Processes Dashboard — список выполняющихся pipeline'ов.

Показывает активные инстансы pipeline'ов, их текущий processor, время начала,
correlation-id. Данные берутся из ExecutionEngine trace-buffer'а.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(
    page_title="Processes", page_icon=":arrows_clockwise:", layout="wide"
)
st.header(":arrows_clockwise: Выполняющиеся процессы")

client = get_api_client()

try:
    active = client._request("GET", "/api/v1/admin/processes/active")  # type: ignore[attr-defined]
except Exception:
    active = []

if not active:
    st.info("Сейчас нет активных pipeline-инстансов.")
else:
    st.caption(f"Активно: {len(active)}")
    for item in active[:50]:
        route = item.get("route_id", "—")
        processor = item.get("current_processor", "—")
        started = item.get("started_at", "")
        corr = item.get("correlation_id", "—")
        cols = st.columns([3, 3, 3, 3])
        cols[0].write(f"**{route}**")
        cols[1].write(f"`{processor}`")
        cols[2].caption(started)
        cols[3].caption(f"`{corr}`")

st.divider()
st.subheader("Статистика за 60 секунд")
try:
    stats = client._request("GET", "/api/v1/admin/processes/stats")  # type: ignore[attr-defined]
    cols = st.columns(4)
    cols[0].metric("Запущено", stats.get("started", 0))
    cols[1].metric("Успешно", stats.get("succeeded", 0))
    cols[2].metric("Ошибок", stats.get("failed", 0))
    cols[3].metric("p95, мс", stats.get("p95_ms", 0))
except Exception:
    st.caption("Статистика недоступна.")
