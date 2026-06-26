"""Saga Compensation Viewer — Sprint 12 K3 W6.

Глубокий анализ saga compensation: timeline view + per-saga drill-down +
aggregated stats.

Источник: workflow_audit ClickHouse через
``get_saga_history`` / ``aggregate_saga_stats``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import streamlit as st

from src.frontend.streamlit_app.shared.components import (
    metric_row,
    related_pages_footer,
    setup_page,
)

setup_page()
st.header("Просмотр Saga Compensation")
st.caption(
    "Timeline saga compensation events (workflow.compensation_* из "
    "workflow_audit). Drill-down по конкретной saga + aggregated stats."
)


col1, col2, col3 = st.columns(3)
tenant_id = col1.text_input("ID тенанта (опц.)", value="")
days_back = col2.slider("Период (дни)", 1, 90, 7)
workflow_id = col3.text_input("ID Workflow (drill-down)", value="")


@st.cache_data(ttl=60)
def _fetch_stats(tenant: str, days: int) -> dict:
    from src.backend.services.dsl_portal import get_saga_stats as aggregate_saga_stats

    to_dt = datetime.now(UTC)
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


st.subheader("Сводная статистика")
try:
    stats = _fetch_stats(tenant_id, days_back)
    metric_row([
        ("Всего saga (рассчитано)", stats["total_sagas"]),
        ("Успешно", stats["succeeded"]),
        ("С ошибкой", stats["failed"]),
        ("Средняя длительность (мс)", f"{stats['avg_duration_ms']:.0f}"),
    ])
except Exception as exc:  # noqa: BLE001
    st.warning(f"Не удалось загрузить stats: {exc}")


if workflow_id:
    st.subheader(f"Таймлайн {workflow_id!r}")
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

related_pages_footer("19_Saga_Компенсации")
