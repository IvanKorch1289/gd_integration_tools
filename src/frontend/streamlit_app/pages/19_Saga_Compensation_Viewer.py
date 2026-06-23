"""Saga Compensation Viewer — Sprint 12 K3 W6.

Глубокий анализ saga compensation: timeline view + per-saga drill-down +
aggregated stats.

Источник: workflow_audit ClickHouse через
``get_saga_history`` / ``aggregate_saga_stats``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Saga Compensation Viewer", "")
st.header("Saga Compensation Viewer")
st.caption(
    "Timeline saga compensation events (workflow.compensation_* из "
    "workflow_audit). Drill-down по конкретной saga + aggregated stats."
)


col1, col2, col3 = st.columns(3)
tenant_id = col1.text_input("Tenant ID (опц.)", value="")
days_back = col2.slider("Period (days)", 1, 90, 7)
workflow_id = col3.text_input("Workflow ID (drill-down)", value="")


@st.cache_data(ttl=60)
def _fetch_stats(tenant: str, days: int) -> dict:
    from src.backend.services.dsl_portal import get_saga_stats as aggregate_saga_stats

    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days)
    return asyncio.run(
        aggregate_saga_stats(tenant_id=tenant or None, from_dt=from_dt, to_dt=to_dt)
    )


@st.cache_data(ttl=60)
def _fetch_history(wf_id: str) -> list:
    from src.backend.services.dsl_portal import get_saga_history

    if not wf_id:
        return []
    records = asyncio.run(get_saga_history(wf_id, limit=100))
    return [
        {
            "event_type": r.event_type,
            "created_at": r.created_at.isoformat(),
            "tenant_id": r.tenant_id,
            "payload": r.payload,
            "duration_ms": r.duration_ms,
        }
        for r in records
    ]


st.subheader("Aggregated stats")
try:
    stats = _fetch_stats(tenant_id, days_back)
    cols = st.columns(4)
    cols[0].metric("Total sagas (рассчитано)", stats["total_sagas"])
    cols[1].metric("Succeeded", stats["succeeded"])
    cols[2].metric("Failed", stats["failed"])
    cols[3].metric("Avg duration (ms)", f"{stats['avg_duration_ms']:.0f}")
except Exception as exc:  # noqa: BLE001
    st.warning(f"Не удалось загрузить stats: {exc}")


if workflow_id:
    st.subheader(f"Timeline {workflow_id!r}")
    try:
        events = _fetch_history(workflow_id)
        if not events:
            st.info("Нет saga compensation events для этого workflow_id.")
        else:
            for ev in events:
                color = {
                    "workflow.compensation_start": "🟦",
                    "workflow.compensation_complete": "🟩",
                    "workflow.compensation_fail": "🟥",
                }.get(ev["event_type"], "·")
                with st.expander(f"{color} {ev['event_type']} @ {ev['created_at']}"):
                    st.json(ev["payload"])
                    if ev.get("duration_ms"):
                        st.caption(f"duration_ms = {ev['duration_ms']}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось загрузить timeline: {exc}")
