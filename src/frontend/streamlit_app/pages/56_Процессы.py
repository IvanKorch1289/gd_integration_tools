"""Processes Dashboard — список выполняющихся pipeline'ов.

Показывает активные инстансы pipeline'ов, их текущий processor, время начала,
correlation-id. Данные берутся из ExecutionEngine trace-buffer'а.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page(layout="wide", initial_sidebar_state="expanded"
)
st.header(":arrows_clockwise: Выполняющиеся процессы")

client = get_api_client()

try:
    with st.spinner("Загрузка процессов..."):
        active = client._request("GET", "/api/v1/admin/processes/active")
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
    stats = client._request("GET", "/api/v1/admin/processes/stats")
    cols = st.columns(4)
    cols[0].metric("Запущено", stats.get("started", 0))
    cols[1].metric("Успешно", stats.get("succeeded", 0))
    cols[2].metric("Ошибок", stats.get("failed", 0))
    cols[3].metric("p95, мс", stats.get("p95_ms", 0))
except Exception:
    st.caption("Статистика недоступна.")

related_pages_footer("56_Процессы")
