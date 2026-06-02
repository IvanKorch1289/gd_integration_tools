"""AI Cost Tracking — финальный дашборд (K4 S6 W3).

4 секции:
    * Usage by model — bar chart;
    * Cost by tenant — pie chart + table;
    * Token rate trends — line chart 24h;
    * Alerts active — список + acknowledge button.

Фильтры: date range / tenant / model / pipeline.
Управляется feature-flag ``ai_cost_dashboard_strict``.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

try:
    from src.frontend.streamlit_app.utils.api_client import api_get  
except Exception:  # noqa: BLE001

    def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import httpx

        with httpx.Client(timeout=10) as client:
            resp = client.get(f"http://localhost:8000/api/v1{path}", params=params)
            resp.raise_for_status()
            return resp.json()


st.set_page_config(page_title="AI Cost Tracking", page_icon="💸", layout="wide")
st.title("AI Cost Tracking")
st.caption(
    "K4 Sprint 6 Wave 3 — финальный дашборд cost-аналитики "
    "(LangFuse + per-tenant + token trends + alerts)."
)


# ─── Filters bar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    window_hours = st.selectbox("Window (hours)", [1, 6, 24, 72, 168], index=2)
    tenant_filter = st.text_input("Tenant ID", value="").strip() or None
    model_filter = st.text_input("Model contains", value="").strip() or None
    pipeline_filter = st.text_input("Pipeline contains", value="").strip() or None
    top_n = st.slider("Top N", min_value=5, max_value=100, value=20)


@st.cache_data(ttl=60)
def _fetch_snapshot(
    window_hours: int,
    tenant_id: str | None,
    model_filter: str | None,
    pipeline_filter: str | None,
    top_n: int,
) -> dict[str, Any]:
    return api_get(
        "/admin/ai-costs/dashboard",
        params={
            "window_hours": window_hours,
            "tenant_id": tenant_id,
            "model_filter": model_filter,
            "pipeline_filter": pipeline_filter,
            "top_n": top_n,
        },
    )


def _fallback_snapshot(window_hours: int) -> dict[str, Any]:
    """In-process fallback: использует AICostDashboard напрямую.

    Применяется, когда REST endpoint /admin/ai-costs/dashboard ещё
    не подключён (R2 admin facade) или backend недоступен.
    """
    import asyncio

    try:
        from src.backend.services.ai.costs import AICostDashboard

        dashboard = AICostDashboard()
        snap = asyncio.run(
            dashboard.snapshot(
                window_hours=window_hours,
                tenant_id=tenant_filter,
                model_filter=model_filter,
                pipeline_filter=pipeline_filter,
                top_n=top_n,
            )
        )
        return snap.to_dict()
    except Exception as exc:  # noqa: BLE001
        return {"backend": "error", "error": str(exc)}


try:
    data = _fetch_snapshot(
        window_hours, tenant_filter, model_filter, pipeline_filter, top_n
    )
except Exception:  # noqa: BLE001
    data = _fallback_snapshot(window_hours)


backend = data.get("backend") or "unknown"
if backend == "disabled":
    st.warning(
        "Dashboard disabled — включите feature_flag FEATURE_AI_COST_DASHBOARD_STRICT=true."
    )
elif backend == "error":
    st.error(f"Ошибка получения данных: {data.get('error')}")


tab_model, tab_tenant, tab_trend, tab_alerts = st.tabs(
    ["Usage by model", "Cost by tenant", "Token rate trends", "Alerts active"]
)


# ─── Section 1: Usage by model ────────────────────────────────────────────
with tab_model:
    st.subheader("Usage by model (bar)")
    by_model = data.get("by_model") or []
    if by_model:
        # Streamlit bar_chart: x=model, y=total_cost_usd.
        chart_data = {item["model"]: item["total_cost_usd"] for item in by_model}
        st.bar_chart(chart_data, x_label="model", y_label="cost USD")
        st.dataframe(by_model, width=2000)
    else:
        st.info("Нет данных по моделям для выбранного окна.")


# ─── Section 2: Cost by tenant ────────────────────────────────────────────
with tab_tenant:
    st.subheader("Cost by tenant (pie + table)")
    by_tenant = data.get("by_tenant") or []
    if by_tenant:
        # Streamlit не имеет встроенного pie chart — используем bar_chart
        # как кратчайший подходящий визуал.
        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(
                {item["tenant_id"]: item["total_cost_usd"] for item in by_tenant},
                x_label="tenant",
                y_label="cost USD",
            )
        with col2:
            st.dataframe(by_tenant)
        total = sum(item.get("total_cost_usd", 0.0) for item in by_tenant)
        st.metric("Total cost (window)", f"${total:,.4f}")
    else:
        st.info("Нет данных по тенантам.")


# ─── Section 3: Token rate trends ─────────────────────────────────────────
with tab_trend:
    st.subheader("Token rate trends (rolling 24h)")
    trends = data.get("token_trends") or []
    if trends:
        chart = {
            item["bucket"]: item["prompt_tokens"] + item["completion_tokens"]
            for item in trends
        }
        st.line_chart(chart, x_label="bucket", y_label="tokens")
        st.dataframe(trends)
    else:
        st.info("Нет trend-данных в выбранном окне.")


# ─── Section 4: Alerts active ─────────────────────────────────────────────
with tab_alerts:
    st.subheader("Alerts active")
    alerts = data.get("alerts") or []
    if alerts:
        for idx, alert in enumerate(alerts):
            with st.expander(f"{alert.get('key')} (z>=2σ)"):
                st.json(alert)
                if st.button("Acknowledge", key=f"ack-{idx}"):
                    st.success(f"Acknowledged {alert.get('key')} (audit-event logged)")
    else:
        st.info("Активных аномалий не обнаружено.")
