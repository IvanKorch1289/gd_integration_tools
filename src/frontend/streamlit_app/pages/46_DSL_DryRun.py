"""DSL Dry-run UI — YAML → execute (mock) → waterfall (S10 K3 W4)."""

from __future__ import annotations

import json
import sys

import streamlit as st
import yaml as _yaml


from src.backend.dsl.engine.dry_run import dry_run_route, waterfall_lines

st.set_page_config(page_title="DSL Dry-Run", page_icon=":fast_forward:", layout="wide")
st.header("DSL Dry-Run")
st.caption(
    "Sprint 10 K3 W4: вставь YAML маршрута, sample JSON-payload и нажми "
    "'Execute (dry-run)' — посмотришь waterfall с per-step latency."
)

col1, col2 = st.columns(2)
with col1:
    st.subheader("YAML route")
    yaml_text = st.text_area(
        "DSL YAML",
        height=400,
        value=(
            "route_id: demo\n"
            "source:\n"
            "  http: { method: POST, path: /api/v1/x }\n"
            "steps:\n"
            "  - call_function: { ref: m:normalize }\n"
            "  - http_call: { url: https://api.test/score }\n"
            "  - audit: { action: scored }\n"
        ),
        key="yaml_input",
    )
with col2:
    st.subheader("Sample payload")
    payload_text = st.text_area(
        "Sample JSON (опционально)",
        height=400,
        value='{"customer_id": 123, "amount": 1000}',
        key="payload_input",
    )

col_run, col_seed = st.columns([3, 1])
with col_run:
    run = st.button("▶ Execute (dry-run)", type="primary")
with col_seed:
    seed = st.number_input("Seed", value=0, step=1)

if run:
    try:
        route = _yaml.safe_load(yaml_text) or {}
    except _yaml.YAMLError as exc:
        st.error(f"YAML parse error: {exc}")
        st.stop()
    if not isinstance(route, dict):
        st.error("YAML root должен быть mapping")
        st.stop()

    payload = None
    if payload_text.strip():
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            st.error(f"JSON parse error: {exc}")
            st.stop()

    result = dry_run_route(route, sample_payload=payload, seed=int(seed))

    st.success(
        f"Dry-run завершён за {result.total_ms:.2f}ms ({len(result.steps)} steps)"
    )

    # Waterfall (ASCII).
    st.subheader("Waterfall")
    st.code("\n".join(waterfall_lines(result, width=40)), language="text")

    # Таблица per-step.
    st.subheader("Per-step latency")
    rows = [
        {
            "idx": s.index,
            "step": s.label,
            "duration_ms": s.duration_ms,
            "output_preview": s.output_preview,
            "notes": "; ".join(s.notes),
        }
        for s in result.steps
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)

    with st.expander("Raw JSON result"):
        st.json(result.to_dict())

st.divider()
st.markdown(
    "**Note:** Dry-run не делает реальных side-effects — latency симулирована "
    "профилем для каждого step-типа. Реальный запуск через "
    "`POST /api/v1/admin/dsl/playground` или `make simulate`."
)
