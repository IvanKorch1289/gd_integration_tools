"""К5 (Wave K5/docs-tenants-caps) — admin-страница per-tenant дашбордов.

Источник данных:

* ``GET /api/v1/admin/tenants``           — список tenants;
* ``GET /api/v1/admin/tenants/{id}``      — детали (RLS, billing, quotas).

В отсутствие живого tenant-registry (Sprint 7+) страница работает в
stub-режиме — отображает пустые секции и подсказку.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client  # noqa: E402
from src.frontend.streamlit_app.shared.components import setup_page

setup_page(
    'Tenants',
    '🏛️',
    layout='wide',
    initial_sidebar_state='expanded',
)
st.header("Tenants — admin dashboard")
st.caption(
    "Per-tenant overview: quotas, billing, SLO, recent audit events. "
    "Источник — `/api/v1/admin/tenants`."
)

client = get_api_client()
tenants_payload = client.get_tenants()

if tenants_payload.get("stub"):
    st.info(
        "Tenant registry в stub-режиме (Sprint 7 К3). "
        "Страница рендерит структуру для будущей интеграции."
    )

tenants_list = tenants_payload.get("tenants") or []

col_total, col_active = st.columns(2)
col_total.metric("Всего tenants", tenants_payload.get("total", 0))
col_active.metric("Активных", sum(1 for t in tenants_list if t.get("active", True)))

st.divider()

selected_id = st.selectbox(
    "Выбрать tenant",
    options=[t.get("tenant_id") for t in tenants_list] or ["(нет)"],
    index=0,
)

if selected_id and selected_id != "(нет)":
    detail = client.get_tenant_detail(selected_id)
    st.subheader(f"Профиль `{selected_id}`")
    cols = st.columns(3)
    cols[0].metric("Plan", detail.get("plan", "—"))
    cols[1].metric("Rate limit", detail.get("rate_limit", "—"))
    cols[2].metric("RLS", "ON" if detail.get("rls_state", {}).get("enabled") else "OFF")

    with st.expander("Quotas"):
        quotas = detail.get("quotas") or []
        if quotas:
            st.dataframe(quotas, use_container_width=True, hide_index=True)
        else:
            st.write("_(нет данных квот)_")

    with st.expander("Recent audit events"):
        events = detail.get("audit_events_recent") or []
        if events:
            st.dataframe(events, use_container_width=True, hide_index=True)
        else:
            st.write("_(нет audit events)_")
