"""Queue Monitor — мониторинг очередей (Kafka/RabbitMQ/Redis Streams).

Отображает lag, размер очередей, DLQ-счётчики. Данные запрашиваются у
admin-эндпоинтов backend'а (`/api/v1/admin/queues/summary`).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import dataframe_view, setup_page

setup_page("Монитор очередей", ":inbox_tray:", layout="wide", initial_sidebar_state="expanded")
st.header(":inbox_tray: Монитор очередей")

client = get_api_client()

auto_refresh = st.toggle("Авто-обновление (10s)", value=False)
if auto_refresh:
    st.caption("Страница обновится автоматически")

try:
    summary = client._request("GET", "/api/v1/admin/queues/summary")
except Exception as exc:  # noqa: BLE001
    summary = {}
    st.warning(f"Не удалось получить сводку: {exc}")

if not summary:
    st.info("Нет данных от backend. Проверьте регистрацию queue-адаптеров.")
else:
    for broker_name, stats in summary.items():
        st.subheader(broker_name)
        cols = st.columns(4)
        cols[0].metric("Topics", stats.get("topics", 0))
        cols[1].metric("Total messages", stats.get("messages", 0))
        cols[2].metric("DLQ", stats.get("dlq", 0))
        cols[3].metric("Consumer lag", stats.get("lag", 0))

        topics = stats.get("topics_detail") or []
        if topics:
            dataframe_view(topics)

if auto_refresh:
    import time

    time.sleep(10)
    st.rerun()
