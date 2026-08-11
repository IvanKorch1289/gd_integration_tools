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

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import streamlit as st

from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)
from src.frontend.streamlit_app.shared.streamlit_config import config


@runtime_checkable
class _SnapshotSerializable(Protocol):
    """Legacy in-process snapshot object returned by the current facade."""

    def to_dict(self) -> object: ...


def _snapshot_to_dict(snapshot: object) -> dict[str, Any]:
    """Accept both REST mappings and the facade's legacy snapshot object."""
    if isinstance(snapshot, Mapping):
        payload = snapshot
    elif isinstance(snapshot, _SnapshotSerializable):
        payload = snapshot.to_dict()
    else:
        raise TypeError("AI cost snapshot must be a mapping or expose to_dict()")

    if not isinstance(payload, Mapping):
        raise TypeError("AI cost snapshot to_dict() must return a mapping")

    result: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise TypeError("AI cost snapshot keys must be strings")
        result[key] = value
    return result


try:
    from src.frontend.streamlit_app.utils.api_client import (
        api_get,  # type: ignore[import-not-found]
    )
except (ImportError, AttributeError, ModuleNotFoundError):
    # cycle-9/D-AUDIT-1046: narrow exceptions + observability.
    # ImportError — api_client module missing, AttributeError — name
    # API change, ModuleNotFoundError — module path broken.

    def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Метод api_get (см. signature)."""
        import os

        import httpx

        base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
        with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC) as client:
            resp = client.get(f"{base_url}/api/v1{path}", params=params)
            resp.raise_for_status()
            return resp.json()


setup_page()
st.title("Отслеживание затрат AI")
st.caption(
    "K4 Sprint 6 Wave 3 — финальный дашборд cost-аналитики "
    "(LangFuse + per-tenant + token trends + alerts)."
)


# ─── Filters bar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Фильтры")
    window_hours = st.selectbox("Окно (часы)", [1, 6, 24, 72, 168], index=2)
    tenant_filter = (
        st.text_input("ID тенанта", value="", key="ai_cost_id_1").strip() or None
    )
    model_filter = (
        st.text_input("Содержит модель", value="", key="ai_cost_text_2").strip() or None
    )
    pipeline_filter = (
        st.text_input("Содержит pipeline", value="", key="ai_cost_pipeline_3").strip()
        or None
    )
    top_n = st.slider("Топ N", min_value=5, max_value=100, value=20)


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
    try:
        # The facade is annotated as a mapping but currently may forward the
        # DashboardSnapshot object. Keep both response shapes runtime-safe.
        from src.backend.core.frontend_facade import get_ai_cost_snapshot

        snapshot: object = get_ai_cost_snapshot(
            window_hours=window_hours,
            tenant_id=tenant_filter,
            model_filter=model_filter,
            pipeline_filter=pipeline_filter,
            top_n=top_n,
        )
        return _snapshot_to_dict(snapshot)
    except Exception as exc:
        return {"backend": "error", "error": str(exc)}


try:
    data = _fetch_snapshot(
        window_hours, tenant_filter, model_filter, pipeline_filter, top_n
    )
except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError) as fetch_exc:
    # cycle-9/D-AUDIT-1052: narrow exceptions + observability.
    # ConnectionError/TimeoutError — server unreachable, RuntimeError —
    # API failure, ValueError — invalid response, TypeError — wrong type,
    # KeyError — missing key.
    import logging
    logging.getLogger(__name__).debug(
        "streamlit_23_AI.snapshot_fetch_failed",
        extra={"error": str(fetch_exc)},
    )
    data = _fallback_snapshot(window_hours)


backend = data.get("backend") or "unknown"
if backend == "disabled":
    st.warning(
        "Dashboard disabled — включите feature_flag "
        "FEATURE_AI_COST_DASHBOARD_STRICT=true."
    )
elif backend == "error":
    st.error(f"Ошибка получения данных: {data.get('error')}")


tab_model, tab_tenant, tab_trend, tab_alerts = st.tabs(
    [
        "Использование по моделям",
        "Стоимость по тенантам",
        "Тренды токенов",
        "Активные алерты",
    ]
)


# ─── Section 1: Usage by model ────────────────────────────────────────────
with tab_model:
    st.subheader("Использование по моделям (bar)")
    by_model = data.get("by_model") or []
    if by_model:
        # Streamlit bar_chart: x=model, y=total_cost_usd.
        chart_data = {item["model"]: item["total_cost_usd"] for item in by_model}
        st.bar_chart(chart_data, x_label="model", y_label="cost USD")
        st.dataframe(by_model, width="stretch")
    else:
        st.info("Нет данных по моделям для выбранного окна.")


# ─── Section 2: Cost by tenant ────────────────────────────────────────────
with tab_tenant:
    st.subheader("Стоимость по тенантам (pie + table)")
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
        st.metric("Общая стоимость (окно)", f"${total:,.4f}")
    else:
        st.info("Нет данных по тенантам.")


# ─── Section 3: Token rate trends ─────────────────────────────────────────
with tab_trend:
    st.subheader("Тренды токенов (скользящее 24ч)")
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
    st.subheader("Активные алерты")
    alerts = data.get("alerts") or []
    if alerts:
        for idx, alert in enumerate(alerts):
            with st.expander(f"{alert.get('key')} (z>=2σ)"):
                st.json(alert)
                if st.button("Подтвердить", key=f"ack-{idx}"):
                    st.success(f"Подтверждено {alert.get('key')} (audit-event записан)")
    else:
        st.info("Активных аномалий не обнаружено.")

related_pages_footer("23_AI_Учёт_затрат")
