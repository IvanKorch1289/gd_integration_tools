"""DSL Dry-run UI — YAML → execute (mock) → waterfall (S10 K3 W4)."""

from __future__ import annotations

import json

import streamlit as st
import yaml as _yaml

from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient
from src.frontend.streamlit_app.shared.components import (
    dataframe_view,
    related_pages_footer,
    setup_page,
)

setup_page()
st.header("Пробный прогон DSL")
st.caption(
    "Sprint 10 K3 W4: вставь YAML маршрута, sample JSON-payload и нажми "
    "'Выполнить (dry-run)' — посмотришь waterfall с per-step latency."
)

col1, col2 = st.columns(2)
with col1:
    st.subheader("YAML маршрута")
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
    st.subheader("Пример payload")
    payload_text = st.text_area(
        "Пример JSON (опционально)",
        height=400,
        value='{"customer_id": 123, "amount": 1000}',
        key="payload_input",
    )

col_run, col_seed = st.columns([3, 1])
with col_run:
    run = st.button("▶ Выполнить (dry-run)", type="primary")
with col_seed:
    seed = st.number_input("Seed", min_value=0, value=0, step=1)

if run:
    try:
        route = _yaml.safe_load(yaml_text) or {}
    except _yaml.YAMLError as exc:
        st.error(f"Ошибка парсинга YAML: {exc}")
        st.stop()
    if not isinstance(route, dict):
        st.error("Корень YAML должен быть mapping")
        st.stop()

    payload = None
    if payload_text.strip():
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            st.error(f"Ошибка парсинга JSON: {exc}")
            st.stop()

    result = DSLRoutesClient().dry_run(route, sample_payload=payload, seed=int(seed))

    if result.get("error"):
        st.error(f"Ошибка dry-run: {result['error']}")
        st.stop()

    st.success(
        f"Dry-run завершён за {result.get('total_ms', 0):.2f}мс "
        f"({len(result.get('steps', []))} шагов)"
    )

    # Waterfall (ASCII).
    st.subheader("Waterfall")
    waterfall = result.get("waterfall", [])
    if waterfall:
        st.code("\n".join(waterfall), language="text")
    else:
        st.info("Нет данных waterfall")

    # Таблица per-step.
    st.subheader("Латентность по шагам")
    rows = [
        {
            "idx": s.get("index"),
            "step": s.get("label"),
            "duration_ms": s.get("duration_ms"),
            "output_preview": s.get("output_preview"),
            "notes": "; ".join(s.get("notes") or []),
        }
        for s in result.get("steps", [])
    ]
    dataframe_view(rows, hide_index=True)

    with st.expander("Сырой JSON результат"):
        st.json(result)

st.divider()
st.markdown(
    "**Замечание:** Dry-run не делает реальных side-effects — латентность симулирована "
    "профилем для каждого типа шага. Реальный запуск через "
    "`POST /api/v1/admin/dsl/playground` или `make simulate`."
)

related_pages_footer("46_DSL_Пробный_прогон")
