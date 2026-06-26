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
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    require_auth,
    setup_page,
)

setup_page()
require_auth(label="write action")
st.header(":shield: Безопасность ИИ / Guardrails")
st.caption(
    "Метрики guardrail-проверок per-tenant: "
    "block_rate, false_positive_rate, per-reason breakdown "
    "(PII / toxic / off-topic / jailbreak)."
)

client = get_api_client()


def _fetch_metrics() -> list[dict]:
    try:
        resp = client.get("/admin/guardrails-metrics")
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить метрики: {exc}")
        return []


metrics = _fetch_metrics()

if not metrics:
    st.info("Нет данных. Guardrails ещё не вызывались либо feature-flag выключен.")
else:
    st.subheader(":bar_chart: Обзор по тенантам")
    overview_cols = st.columns(4)
    total = sum(m["total"] for m in metrics)
    total_block = sum(m["block"] for m in metrics)
    total_fp = sum(m["false_positives"] for m in metrics)
    overall_block_rate = total_block / total if total else 0.0
    overall_fp_rate = total_fp / total_block if total_block else 0.0
    overview_cols[0].metric("Всего проверок", total)
    overview_cols[1].metric("Всего блокировок", total_block)
    overview_cols[2].metric("Доля блокировок", f"{overall_block_rate:.2%}")
    overview_cols[3].metric("Доля FP", f"{overall_fp_rate:.2%}")

    st.divider()
    st.subheader(":mag: Детали по тенантам")
    for metric in metrics:
        with st.expander(
            f":busts_in_silhouette: {metric['tenant_id']} — "
            f"{metric['total']} проверок "
            f"({metric['block_rate']:.1%} блокировок)",
            expanded=metric["block_rate"] > 0.20,
        ):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Разрешено", metric["allow"])
            col_b.metric("Заблокировано", metric["block"])
            col_c.metric("Отредактировано", metric["redact"])

            st.write("**Причины блокировок:**")
            for reason, count in metric.get("by_reason", {}).items():
                st.write(f"- {reason}: {count}")

            fp_count = st.number_input(
                "Отметить как false-positive (количество)",
                min_value=0,
                value=0,
                key=f"fp-{metric['tenant_id']}",
            )
            if fp_count > 0 and st.button(
                "Отправить FP-ревью", key=f"submit-fp-{metric['tenant_id']}"
            ):
                try:
                    client.post(
                        f"/admin/guardrails-metrics/{metric['tenant_id']}/false-positive",
                        json={"count": int(fp_count)},
                    ).raise_for_status()
                    st.success(f"Записано {fp_count} FP для {metric['tenant_id']}")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка отправки: {exc}")

related_pages_footer("47_AI_Безопасность")
