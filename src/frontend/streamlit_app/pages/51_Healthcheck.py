"""Healthcheck Dashboard — статусы всех подсистем в одном экране.

Собирает данные из ``GET /ready`` (агрегированный отчёт :class:`HealthAggregator`)
и рендерит плитки: зелёная / жёлтая / красная по ``status``.
"""

from __future__ import annotations

import time

import streamlit as st

from src.frontend.streamlit_app.api_clients import AdminClient

st.set_page_config(page_title="Healthcheck", page_icon=":heart:", layout="wide")
st.header(":heart: Healthcheck Dashboard")

auto = st.toggle("Авто-обновление (5s)", value=True)

client = AdminClient()

try:
    data = client.get_ready()
except Exception as exc:  # noqa: BLE001
    data = {"status": "error", "components": {}}
    st.error(f"Не удалось получить /ready: {exc}")

overall = data.get("status", "unknown")
colors = {
    "ok": ":green_circle:",
    "degraded": ":large_orange_circle:",
    "down": ":red_circle:",
    "error": ":red_circle:",
}

st.subheader(f"{colors.get(overall, ':grey_question:')} Overall: **{overall.upper()}**")
st.caption(f"Timestamp: {data.get('timestamp', '—')}")

components = data.get("components", {}) or {}
cols = st.columns(3)
for idx, (name, info) in enumerate(sorted(components.items())):
    status = info.get("status", "unknown")
    latency = info.get("latency_ms")
    with cols[idx % 3]:
        st.markdown(f"{colors.get(status, ':grey_question:')} **{name}**")
        if latency is not None:
            st.caption(f"{latency:.1f} ms")
        if info.get("error"):
            st.caption(f":warning: {info['error'][:120]}")
        else:
            st.caption(status)

if auto:
    time.sleep(5)
    st.rerun()
