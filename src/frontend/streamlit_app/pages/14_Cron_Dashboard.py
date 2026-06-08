"""Cron Schedule Dashboard — Sprint 12 K5 W3.

Сводный dashboard для всех scheduled workflows:

* Таблица: name, cron_expr, tz, last_run_at, next_run_at, success_rate(7d),
  status (enabled/paused).
* Action кнопки per row: Pause / Resume / Run now / Delete.
* Top-level metrics: total scheduled / today runs / today failed.
* Auto-refresh каждые 30 сек.
"""

from __future__ import annotations

import asyncio

import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Cron Dashboard", "")
st.header("Cron Schedule Dashboard — Sprint 12 K5 W3")
st.caption(
    "Все scheduled workflows: cron-expr, next/last run, success rate (7d). "
    "Auto-refresh каждые 30 секунд."
)


try:
    import streamlit_autorefresh

    streamlit_autorefresh.st_autorefresh(interval=30000, key="cron_refresh")
except ImportError:
    pass


@st.cache_data(ttl=20)
def _load_dashboard() -> list[dict]:
    from src.backend.services.scheduler.cron_dashboard_service import (
        CronDashboardService,
    )

    service = CronDashboardService()
    items = asyncio.run(service.list_scheduled())
    return [
        {
            "id": x.id,
            "name": x.name,
            "cron_expr": x.cron_expr,
            "timezone": x.timezone,
            "next_run_at": x.next_run_at,
            "last_run_at": x.last_run_at,
            "success_rate_7d": x.success_rate_7d,
            "status": x.status,
        }
        for x in items
    ]


try:
    items = _load_dashboard()
except Exception as exc:  # noqa: BLE001
    items = []
    st.warning(f"Не удалось загрузить dashboard: {exc}")

total = len(items)
paused = sum(1 for i in items if i["status"] == "paused")
enabled = total - paused

col1, col2, col3 = st.columns(3)
col1.metric("Total scheduled", total)
col2.metric("Enabled", enabled)
col3.metric("Paused", paused)

st.divider()

if not items:
    st.info("Нет зарегистрированных cron-jobs.")
else:
    for item in items:
        with st.expander(
            f"📅 {item['name']} — {item['cron_expr']} "
            f"({item['timezone']}) — {item['status']}"
        ):
            cols = st.columns(5)
            cols[0].caption(f"**ID**: `{item['id']}`")
            cols[1].caption(f"**Next**: {item['next_run_at'] or '—'}")
            cols[2].caption(f"**Last**: {item['last_run_at'] or '—'}")
            cols[3].caption(f"**Success rate (7d)**: {item['success_rate_7d']:.1f}%")

            actions = st.columns(4)
            try:
                import httpx as requests

                from src.frontend.streamlit_app.api_clients import get_api_client

                client = get_api_client()
                base_url = getattr(client, "base_url", "http://localhost:8000")

                if item["status"] == "paused":
                    if actions[0].button("Resume", key=f"resume_{item['id']}"):
                        resp = requests.post(
                            f"{base_url}/api/v1/admin/cron/{item['id']}/resume",
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            st.success("Resumed")
                            st.rerun()
                else:
                    if actions[0].button("Pause", key=f"pause_{item['id']}"):
                        resp = requests.post(
                            f"{base_url}/api/v1/admin/cron/{item['id']}/pause",
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            st.success("Paused")
                            st.rerun()

                if actions[1].button("Run now", key=f"run_{item['id']}"):
                    resp = requests.post(
                        f"{base_url}/api/v1/admin/cron/{item['id']}/run-now", timeout=5
                    )
                    if resp.status_code == 200:
                        st.success("Scheduled for immediate execution")

                if actions[2].button(
                    "Delete", key=f"del_{item['id']}", type="secondary"
                ):
                    resp = requests.delete(
                        f"{base_url}/api/v1/admin/cron/{item['id']}", timeout=5
                    )
                    if resp.status_code == 204:
                        st.success("Deleted")
                        st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Action failed: {exc}")
