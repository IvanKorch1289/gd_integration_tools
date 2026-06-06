"""AI Safety / Guardrails dashboard (Sprint 9 K4 W5 — GAP-AI-3.8).

Аггрегация метрик guardrail-проверок per-tenant:

* block_rate (текущий тренд + threshold)
* false_positive_rate
* per-reason breakdown (PII / toxic / off-topic / jailbreak / ...)
* mark FP кнопка для operator review

Feature-flag: ``feature_flags.ai_safety_panel_enabled`` (default-OFF).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client

st.set_page_config(page_title="AI Safety", page_icon=":shield:", layout="wide")
st.header(":shield: AI Safety / Guardrails")

client = get_api_client()


def _fetch_metrics() -> list[dict]:
    try:
        resp = client.get("/admin/guardrails-metrics")
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch metrics: {exc}")
        return []


metrics = _fetch_metrics()

if not metrics:
    st.info("Нет данных. Guardrails ещё не вызывались либо feature-flag выключен.")
else:
    st.subheader(":bar_chart: Per-tenant overview")
    overview_cols = st.columns(4)
    total = sum(m["total"] for m in metrics)
    total_block = sum(m["block"] for m in metrics)
    total_fp = sum(m["false_positives"] for m in metrics)
    overall_block_rate = total_block / total if total else 0.0
    overall_fp_rate = total_fp / total_block if total_block else 0.0
    overview_cols[0].metric("Total checks", total)
    overview_cols[1].metric("Total blocked", total_block)
    overview_cols[2].metric("Block rate", f"{overall_block_rate:.2%}")
    overview_cols[3].metric("FP rate", f"{overall_fp_rate:.2%}")

    st.divider()
    st.subheader(":mag: Per-tenant detail")
    for metric in metrics:
        with st.expander(
            f":busts_in_silhouette: {metric['tenant_id']} — "
            f"{metric['total']} checks "
            f"({metric['block_rate']:.1%} blocked)",
            expanded=metric["block_rate"] > 0.20,
        ):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Allow", metric["allow"])
            col_b.metric("Block", metric["block"])
            col_c.metric("Redact", metric["redact"])

            st.write("**Block reasons:**")
            for reason, count in metric.get("by_reason", {}).items():
                st.write(f"- {reason}: {count}")

            fp_count = st.number_input(
                "Mark as false-positive (count)",
                min_value=0,
                value=0,
                key=f"fp-{metric['tenant_id']}",
            )
            if fp_count > 0 and st.button(
                "Submit FP review", key=f"submit-fp-{metric['tenant_id']}"
            ):
                try:
                    client.post(
                        f"/admin/guardrails-metrics/{metric['tenant_id']}/false-positive",
                        json={"count": int(fp_count)},
                    ).raise_for_status()
                    st.success(f"Recorded {fp_count} FPs for {metric['tenant_id']}")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Submit failed: {exc}")
