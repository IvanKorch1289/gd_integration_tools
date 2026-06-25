"""Workflow Cost Estimation — Sprint 12 K3 W3 + K4 W2.

Pre-run cost estimation для workflow по historical данным workflow_audit
ClickHouse + LLM breakdown по моделям (K4 W2).

Источник правды: ``WorkflowCostEstimator`` через
``POST /admin/workflow-cost/estimate``.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Оценка стоимости Workflow", "")
st.header("Оценка стоимости Workflow")

st.caption(
    "Pre-run estimation для workflow на основе p50/p95 historical "
    "duration_ms из workflow_audit. AI breakdown по моделям (gpt-4o / "
    "claude-sonnet / opus) — K4 W2."
)

client = get_api_client()

try:
    from src.backend.services.dsl_portal import get_global_registry

    all_ids = sorted(get_global_registry().all_workflow_ids())
except Exception:  # noqa: BLE001
    all_ids = []

workflow_id = st.selectbox(
    "ID Workflow",
    options=all_ids + ["(введите вручную)"] if all_ids else ["(введите вручную)"],
    key="cost_wf",
)
if workflow_id == "(введите вручную)":
    workflow_id = st.text_input("workflow_id", value="")

version = st.text_input("Версия (опц.)", value="")
input_size = st.number_input(
    "Размер входного payload (байт)", min_value=0, value=1024, step=1024
)
sample_period_days = st.slider(
    "Исторический период (дни)", min_value=1, max_value=90, value=30
)

if st.button("Оценить", type="primary", disabled=not workflow_id):
    try:
        import httpx as requests

        base_url = getattr(client, "base_url", "http://localhost:8000")
        payload = {
            "workflow_id": workflow_id,
            "input_size_bytes": int(input_size),
            "sample_period_days": int(sample_period_days),
        }
        if version:
            payload["version"] = version
        resp = requests.post(
            f"{base_url}/api/v1/admin/workflow-cost/estimate", json=payload, timeout=10
        )
        if resp.status_code != 200:
            st.error(f"HTTP {resp.status_code}: {resp.text}")
        else:
            body = resp.json()
            st.subheader("Оценка")
            tab_main, tab_ai = st.tabs(["Обзор", "Разбивка по ИИ"])
            with tab_main:
                col1, col2, col3 = st.columns(3)
                col1.metric("p50 длительность (мс)", f"{body['p50_duration_ms']:.0f}")
                col2.metric("p95 длительность (мс)", f"{body['p95_duration_ms']:.0f}")
                col3.metric("Размер выборки", body["sample_size"])
                col4, col5 = st.columns(2)
                col4.metric(
                    "Вычисления (сек)", f"{body['estimated_compute_seconds']:.2f}"
                )
                col5.metric("Хранилище (байт)", body["estimated_storage_bytes"])

            with tab_ai:
                breakdown = body.get("llm_breakdown")
                if not breakdown:
                    st.info(
                        "Workflow не содержит LLM-activity или registry не "
                        "знает declaration."
                    )
                else:
                    st.metric("Всего токенов", breakdown["total_tokens"])
                    st.metric("Общая стоимость (USD)", f"${breakdown['total_usd']}")
                    st.subheader("По моделям")
                    for model, cost in breakdown["per_model"].items():
                        st.write(f"**{model}**: ${cost}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка оценки: {exc}")
