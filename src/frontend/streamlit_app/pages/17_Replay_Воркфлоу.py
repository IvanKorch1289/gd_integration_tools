"""Streamlit страница: Workflow Replay — drill-down на event-timeline (Sprint 4 Wave F).

Назначение:
    Replay-визуализация Temporal-workflow events для отладки и audit-трейла.
    Дополняет существующую 16_Workflows.py (общий dashboard) фокусом на
    timeline + waterfall-диаграмме исполнения.

Функционал:
    1. Sidebar — поиск workflow по ID или выбор из списка.
    2. Header — текущий статус + параметры запуска (input payload).
    3. Body — таблица events с timestamp/type/attributes + waterfall-chart.
    4. Filters — по event-type и временному диапазону.

Используемые endpoints (уже доступны):
    * GET /api/v1/admin/workflows — список.
    * GET /api/v1/admin/workflows/{id} — header.
    * GET /api/v1/admin/workflows/{id}/events?page=&size= — paginated events.

Все строки UI — на русском языке (CLAUDE.md правило).
"""

# ruff: noqa: B008

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared import (  # Sprint 43 W2 (TD-008 Group 3)
    dataframe_view,
    date_range_filter,
    multiselect_filter,
    setup_page,
)

setup_page("Воспроизведение Workflow · gd_integration_tools", "⏯️")
client = get_api_client()


@st.cache_data(ttl=15)
def _list_workflow_ids(limit: int = 50) -> list[str]:
    """Получить список workflow IDs (cache-friendly)."""
    try:
        rows = client.list_workflows(page=1, size=limit)
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("data") or []
        return [
            str(row.get("id") or row.get("instance_id") or row.get("workflow_id"))
            for row in rows
            if isinstance(row, dict)
        ]
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить список workflows: {exc}")
        return []


def _fetch_events(workflow_id: str, page: int, size: int) -> list[dict[str, Any]]:
    """Получить events с пагинацией."""
    try:
        result = client.get_workflow_events(workflow_id, page=page, size=size)
        if isinstance(result, dict):
            return list(result.get("items") or result.get("data") or [])
        return list(result or [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить events: {exc}")
        return []


def _render_event_filters(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Отрендерить фильтры event-type / date и вернуть отфильтрованный список.

    Sprint 43 W2 (TD-008 Group 3): использует `multiselect_filter` +
    `date_range_filter` из `shared.filters` вместо inline `st.columns` +
    `st.multiselect` + 2× `st.date_input` boilerplate.
    """
    if not events:
        return events

    event_types = sorted(
        {str(e.get("event_type") or e.get("type") or "?") for e in events}
    )

    selected_types = multiselect_filter(
        "Типы событий", options=event_types, default=event_types
    )
    from_date, to_date = date_range_filter("Период", key_prefix="wf_replay")

    def _matches(event: dict[str, Any]) -> bool:
        if selected_types and (
            str(event.get("event_type") or event.get("type") or "?")
            not in selected_types
        ):
            return False
        timestamp_raw = event.get("timestamp") or event.get("ts")
        if timestamp_raw and (from_date or to_date):
            try:
                ts = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
            except ValueError:
                return True
            if from_date and ts.date() < from_date:
                return False
            if to_date and ts.date() > to_date:
                return False
        return True

    return [e for e in events if _matches(e)]


def main() -> None:
    """Точка входа Streamlit-страницы."""
    st.title("⏯️ Воспроизведение Workflow")
    st.caption(
        "Drill-down на event-timeline конкретного Temporal-workflow для "
        "отладки и audit-трейла. Sprint 4 Wave F."
    )

    with st.sidebar:
        st.header("Выбор workflow")
        workflow_ids = _list_workflow_ids()
        manual_id = st.text_input("Workflow ID (или выбор из списка ↓)", value="")
        chosen_from_list = st.selectbox(
            "Из последних", options=[""] + workflow_ids, index=0
        )
        workflow_id = manual_id.strip() or chosen_from_list

        st.divider()
        page = st.number_input("Страница", min_value=1, value=1, step=1)
        size = st.slider("Events / страницу", min_value=10, max_value=200, value=50)

    if not workflow_id:
        st.info(
            "Введите Workflow ID в sidebar или выберите из списка для запуска replay."
        )
        return

    events = _fetch_events(workflow_id, int(page), int(size))
    if not events:
        st.warning(f"Events не найдены для workflow_id={workflow_id!r}")
        return

    st.subheader(f"Events для workflow `{workflow_id}`")
    filtered = _render_event_filters(events)
    st.caption(f"Всего после фильтров: **{len(filtered)}** / {len(events)}")

    # Таблица events.
    dataframe_view(filtered, hide_index=True)

    # Waterfall (упрощённый — st.bar_chart по count типов).
    if filtered:
        type_counts: dict[str, int] = {}
        for ev in filtered:
            key = str(ev.get("event_type") or ev.get("type") or "?")
            type_counts[key] = type_counts.get(key, 0) + 1
        st.subheader("Распределение по типам события")
        st.bar_chart(type_counts)


main()


# ──────────────────────── Sprint 12 K3 W6: Saga Compensation ─────────────
st.divider()
st.subheader("🔄 Saga Compensation")
st.caption(
    "Sprint 12 K3 W6 — timeline saga compensation events. Полный анализ "
    "→ page 19 (Saga Compensation Viewer)."
)

_wf_id_compens = st.text_input("Workflow ID для saga timeline", key="saga_wf_id")

if _wf_id_compens:
    try:
        # S6 fix: facade через dsl_portal (R3.10d / S36).
        from src.backend.services.dsl_portal import get_saga_history

        records = get_saga_history(_wf_id_compens, limit=50)
    except Exception as exc:  # noqa: BLE001
        records = []
        st.warning(f"Saga history недоступна: {exc}")

    if not records:
        st.info("Нет saga compensation events.")
    else:
        for rec in records:
            color = {
                "workflow.compensation_start": "🟦",
                "workflow.compensation_complete": "🟩",
                "workflow.compensation_fail": "🟥",
            }.get(rec.event_type, "·")
            with st.expander(
                f"{color} {rec.event_type} @ {rec.created_at.isoformat()}"
            ):
                st.json(rec.payload)
                if rec.duration_ms is not None:
                    st.caption(f"duration_ms = {rec.duration_ms}")
