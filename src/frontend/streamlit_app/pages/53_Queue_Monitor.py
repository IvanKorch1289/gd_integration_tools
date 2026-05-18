"""Queue Monitor — мониторинг очередей (Kafka/RabbitMQ/Redis Streams).

Отображает lag, размер очередей, DLQ-счётчики. Данные запрашиваются у
admin-эндпоинтов backend'а (`/api/v1/admin/queues/summary`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Queues", page_icon=":inbox_tray:", layout="wide")
st.header(":inbox_tray: Queue Monitor")

client = get_api_client()

auto_refresh = st.toggle("Авто-обновление (10s)", value=False)
if auto_refresh:
    st.caption("Страница обновится автоматически")

try:
    summary = client._request("GET", "/api/v1/admin/queues/summary")  # type: ignore[attr-defined]
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
            st.dataframe(topics, use_container_width=True)

if auto_refresh:
    import time

    time.sleep(10)
    st.rerun()
