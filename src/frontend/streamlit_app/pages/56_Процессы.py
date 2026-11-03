"""Processes Dashboard — список выполняющихся pipeline'ов.

Показывает активные инстансы pipeline'ов, их текущий processor, время начала,
correlation-id. Данные берутся из ExecutionEngine trace-buffer'а.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    metric_row,
    related_pages_footer,
    setup_page,
)

setup_page(layout="wide", initial_sidebar_state="expanded")
st.header(":arrows_clockwise: Выполняющиеся процессы")

client = get_api_client()

# Активные инстансы на сервере не отдаются (ADR-0425) — endpoint'а нет.
st.info(
    "Активные pipeline-инстансы недоступны: серверный endpoint "
    "`GET /api/v1/admin/processes/active` не реализован."
)
active: list[dict[str, object]] = []

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
# Статистика процессов на сервере не отдаётся (ADR-0425) — endpoint'а нет.
st.info(
    "Статистика процессов недоступна: серверный endpoint "
    "`GET /api/v1/admin/processes/stats` не реализован."
)
metric_row([("Запущено", 0), ("Успешно", 0), ("Ошибок", 0), ("p95, мс", 0)])

related_pages_footer("56_Процессы")
