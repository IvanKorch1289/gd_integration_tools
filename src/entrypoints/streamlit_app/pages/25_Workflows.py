"""Streamlit страница: Durable Workflows runtime dashboard (IL-WF4).

Три блока (tabs):
  1. **Instances** — список pending/running/paused/succeeded/failed/
     cancelled с фильтрами и paging. Для каждого: retry / cancel / resume
     buttons.
  2. **Timeline** — drill-down: при выборе instance показывается event-
     timeline (Mermaid / Plotly Gantt) + текущая позиция.
  3. **Trigger** — форма запуска нового workflow по имени + JSON payload.

Дизайн идиоматичен существующим страницам (7_Jobs.py, 2_Routes.py) —
`@st.cache_data(ttl=5)` для снижения API-трафика, цветные метки статусов,
раскрывающиеся expanders для деталей.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import streamlit as st

from src.entrypoints.streamlit_app.api_client import get_api_client


st.set_page_config(
    page_title="Workflows · gd_integration_tools",
    page_icon="🔁",
    layout="wide",
)

client = get_api_client()


# -- Helpers -----------------------------------------------------------


STATUS_BADGES: dict[str, tuple[str, str]] = {
    "pending": ("🟡", "#6C757D"),
    "running": ("🔵", "#0D6EFD"),
    "paused": ("⏸", "#FFC107"),
    "succeeded": ("✅", "#198754"),
    "failed": ("❌", "#DC3545"),
    "cancelling": ("⏳", "#FD7E14"),
    "cancelled": ("🚫", "#6C757D"),
    "compensating": ("🔄", "#20C997"),
}

EVENT_ICONS: dict[str, str] = {
    "created": "🎬",
    "step_started": "▶",
    "step_finished": "✔",
    "step_failed": "✖",
    "branch_taken": "🔀",
    "loop_iter": "🔁",
    "sub_spawned": "⤵",
    "sub_completed": "⤴",
    "paused": "⏸",
    "resumed": "▶",
    "cancelled": "🚫",
    "compensated": "↩",
    "snapshotted": "📸",
}


@st.cache_data(ttl=5)
def _cached_list(status: str | None, name: str | None, tenant: str | None, limit: int) -> list[dict[str, Any]]:
    return client.list_workflows(
        status=status or None,
        workflow_name=name or None,
        tenant_id=tenant or None,
        limit=limit,
    )


@st.cache_data(ttl=3)
def _cached_instance(instance_id: str) -> dict[str, Any] | None:
    return client.get_workflow(instance_id)


@st.cache_data(ttl=3)
def _cached_events(instance_id: str, after_seq: int, limit: int) -> list[dict[str, Any]]:
    return client.get_workflow_events(instance_id, after_seq=after_seq, limit=limit)


def _status_label(status: str) -> str:
    icon, _ = STATUS_BADGES.get(status, ("❔", "#888"))
    return f"{icon} {status}"


def _fmt_timestamp(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        # API returns ISO-8601
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            return value
    return str(value)


# -- UI ---------------------------------------------------------------


st.title("🔁 Durable Workflows")
st.caption(
    "Admin dashboard для durable workflow instances. "
    "Источник данных — `/api/v1/admin/workflows` (IL-WF1.5)."
)

tab_list, tab_timeline, tab_trigger = st.tabs(
    ["📋 Instances", "📈 Timeline", "🚀 Trigger"]
)

# ======================================================================
# Tab 1 — Instances list
# ======================================================================

with tab_list:
    cols_filter = st.columns([1, 1, 1, 1, 1])
    with cols_filter[0]:
        flt_status = st.selectbox(
            "Status",
            options=[""] + list(STATUS_BADGES.keys()),
            index=0,
        )
    with cols_filter[1]:
        flt_name = st.text_input("Workflow name", value="", placeholder="orders.skb_flow")
    with cols_filter[2]:
        flt_tenant = st.text_input("Tenant", value="", placeholder="default")
    with cols_filter[3]:
        flt_limit = st.number_input("Limit", min_value=10, max_value=500, value=100, step=10)
    with cols_filter[4]:
        st.write("")  # spacer
        if st.button("🔄 Refresh", use_container_width=True):
            _cached_list.clear()

    instances = _cached_list(flt_status, flt_name, flt_tenant, int(flt_limit))

    if not instances:
        st.info("Нет instances по заданным фильтрам.")
    else:
        st.caption(f"Найдено: **{len(instances)}** instances")

        for inst in instances:
            icon, color = STATUS_BADGES.get(inst.get("status", ""), ("❔", "#888"))
            header = (
                f"{icon} **{inst.get('workflow_name', '?')}** "
                f"`{inst.get('id', '')[:8]}` "
                f"— status={inst.get('status', '?')}"
            )
            with st.expander(header, expanded=False):
                cols = st.columns([2, 2, 1, 1, 1])
                cols[0].metric("Created", _fmt_timestamp(inst.get("created_at")))
                cols[1].metric("Next attempt", _fmt_timestamp(inst.get("next_attempt_at")))
                cols[2].metric("Attempts", inst.get("attempts", 0))
                cols[3].metric("Tenant", inst.get("tenant_id", "default"))
                cols[4].metric("Version", inst.get("current_version", 0))

                # Actions
                action_cols = st.columns([1, 1, 1, 3])
                instance_id = inst.get("id", "")
                if action_cols[0].button("🔁 Retry", key=f"retry_{instance_id}"):
                    if client.retry_workflow(instance_id):
                        st.success("Запланирован retry. Обновите список.")
                        _cached_list.clear()
                    else:
                        st.error("Retry failed.")
                if action_cols[1].button("🚫 Cancel", key=f"cancel_{instance_id}"):
                    if client.cancel_workflow(instance_id, reason="admin UI"):
                        st.success("Cancel queued.")
                        _cached_list.clear()
                    else:
                        st.error("Cancel failed.")
                if action_cols[2].button("▶ Resume", key=f"resume_{instance_id}"):
                    if client.resume_workflow(instance_id):
                        st.success("Resumed.")
                        _cached_list.clear()
                    else:
                        st.error("Resume failed.")
                if action_cols[3].button("📈 View Timeline", key=f"tl_{instance_id}"):
                    st.session_state["_workflow_focus_id"] = instance_id


# ======================================================================
# Tab 2 — Timeline (event log)
# ======================================================================

with tab_timeline:
    focus_id = st.text_input(
        "Instance ID",
        value=st.session_state.get("_workflow_focus_id", ""),
        placeholder="UUID",
    )
    if not focus_id:
        st.info("Введите instance ID или выберите «View Timeline» из вкладки Instances.")
    else:
        instance = _cached_instance(focus_id)
        events = _cached_events(focus_id, 0, 500)

        if instance is None:
            st.error(f"Instance {focus_id} не найден.")
        else:
            # Header
            colh = st.columns([2, 2, 1, 1])
            colh[0].metric("Workflow", instance.get("workflow_name", "—"))
            colh[1].metric("Status", _status_label(instance.get("status", "?")))
            colh[2].metric("Events", len(events))
            colh[3].metric("Attempts", instance.get("attempts", 0))

            # Event timeline
            st.subheader(f"📜 Event log ({len(events)} events)")
            if not events:
                st.caption("_No events yet._")
            else:
                for ev in events:
                    ev_icon = EVENT_ICONS.get(ev.get("event_type", ""), "•")
                    step = ev.get("step_name") or "—"
                    seq = ev.get("seq", "?")
                    ts = _fmt_timestamp(ev.get("occurred_at"))
                    st.markdown(
                        f"**{ev_icon} seq={seq}** · `{ev.get('event_type', '?')}` "
                        f"· step=`{step}` · {ts}"
                    )
                    if ev.get("payload"):
                        with st.expander("payload", expanded=False):
                            st.json(ev["payload"])

            # Snapshot state (if available)
            if instance.get("snapshot_state"):
                st.subheader("📸 Snapshot state")
                with st.expander("state JSON", expanded=False):
                    st.json(instance["snapshot_state"])


# ======================================================================
# Tab 3 — Trigger new workflow
# ======================================================================

with tab_trigger:
    st.caption(
        "Запуск нового workflow instance через `POST /api/v1/admin/workflows/trigger/{name}`."
    )

    trg_name = st.text_input("Workflow name", value="", placeholder="orders.full_processing")
    payload_str = st.text_area(
        "Input payload (JSON)",
        value="{}",
        height=200,
        placeholder='{"order_id": 123, "email_for_answer": "user@example.com"}',
    )
    col_opts = st.columns([1, 1, 3])
    wait = col_opts[0].checkbox("Wait (sync)", value=False)
    timeout_s = col_opts[1].number_input("Timeout (s)", min_value=5, max_value=600, value=30, step=5)

    if st.button("🚀 Trigger", type="primary"):
        if not trg_name:
            st.error("Укажите workflow name.")
        else:
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON: {exc}")
                payload = None

            if payload is not None:
                result = client.trigger_workflow(
                    trg_name, payload, wait=wait, timeout_s=int(timeout_s)
                )
                if result is None:
                    st.error("Trigger failed (check API error logs).")
                else:
                    st.success("Triggered!")
                    st.json(result)
                    if result.get("id"):
                        st.session_state["_workflow_focus_id"] = result["id"]
                        st.caption("➡ Переключитесь на вкладку **Timeline** для просмотра.")

    st.markdown("---")
    st.caption(
        "**Tip:** список зарегистрированных workflows доступен через MCP tool "
        "`workflow_list` или через admin-UI `/api/v1/admin/workflows` фильтрацией "
        "по `workflow_name`."
    )
