"""Healthcheck Dashboard — статусы всех подсистем в одном экране.

Собирает данные из ``GET /ready`` (агрегированный отчёт :class:`HealthAggregator`)
и рендерит плитки: зелёная / жёлтая / красная по ``status``.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import AdminClient
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page(layout="wide", initial_sidebar_state="expanded")
st.header(":heart: Дашборд проверки состояния")

auto = st.toggle("Авто-обновление (5s)", value=True)
client = AdminClient()


@st.fragment(run_every="5s")
def _render_health_dashboard() -> None:
    """Auto-refresh healthcheck fragment (Streamlit 1.33+ run_every).

    Заменяет ``time.sleep + st.rerun()`` pattern (freezes Streamlit thread).
    """
    try:
        with st.spinner("Проверка состояния..."):
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

    if not auto:
        st.caption("⏸ Авто-обновление отключено")


_render_health_dashboard()

related_pages_footer("51_Проверка_здоровья")
