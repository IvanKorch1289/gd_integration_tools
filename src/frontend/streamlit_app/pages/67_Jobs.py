"""Background Job Dashboard — APScheduler + queues + webhooks."""

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Задачи", ":gear:")
st.header("Фоновые задачи")

client = get_api_client()

tab1, tab2, tab3 = st.tabs(["Запланированные", "Глубина очередей", "Webhooks"])

# ─────────── Scheduled Jobs (APScheduler) ───────────

with tab1:
    st.subheader("Задачи APScheduler")
    try:
        jobs = client._request("GET", "/api/v1/admin/scheduler/jobs")
    except Exception as exc:
        st.error(f"Ошибка: {exc}")
        jobs = []

    if jobs:
        import polars as pl

        df = pl.DataFrame(jobs)
        st.dataframe(df, use_container_width=True)
        st.caption(f"Всего: {len(jobs)} jobs")
    else:
        st.info("Нет запланированных задач")

# ─────────── Queue Depths ───────────

with tab2:
    st.subheader("Глубина очередей (RabbitMQ/Kafka)")
    try:
        queues = client._request("GET", "/api/v1/admin/queue/stats")
    except Exception:
        queues = {}

    if queues:
        cols = st.columns(min(len(queues), 4))
        for i, (name, depth) in enumerate(queues.items()):
            with cols[i % len(cols)]:
                st.metric(name, depth)
    else:
        st.info("Нет активных очередей")

# ─────────── Scheduled Webhooks ───────────

with tab3:
    st.subheader("Запланированные webhooks")
    try:
        hooks = client._request("GET", "/api/v1/webhooks/scheduled")
    except Exception:
        hooks = []

    if hooks:
        import polars as pl

        df = pl.DataFrame(hooks)
        display_cols = [
            c
            for c in ["id", "url", "cron", "delay_seconds", "status"]
            if c in df.columns
        ]
        st.dataframe(
            df.select(display_cols) if display_cols else df, use_container_width=True
        )
    else:
        st.info("Нет запланированных webhooks")

    st.divider()
    with st.expander("Запланировать webhook"):
        with st.form("schedule_webhook"):
            url = st.text_input("URL")
            payload = st.text_area("Payload (JSON)", value="{}")
            cron = st.text_input("Cron (опционально)", placeholder="*/5 * * * *")
            delay = st.number_input("Задержка, сек (опционально)", min_value=0, value=0)
            if st.form_submit_button("Запланировать"):
                import json

                try:
                    payload_dict = json.loads(payload)
                    result = client._request(
                        "POST",
                        "/api/v1/webhook/schedule",
                        json={
                            "url": url,
                            "payload": payload_dict,
                            "cron": cron or None,
                            "delay_seconds": delay if delay > 0 else None,
                        },
                    )
                    st.success(f"Запланировано: {result}")
                except Exception as exc:
                    st.error(f"Ошибка: {exc}")

if st.button("Обновить"):
    st.rerun()
