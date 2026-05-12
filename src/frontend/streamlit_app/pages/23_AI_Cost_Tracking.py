"""AI Cost Tracking — LangFuse-powered dashboard (Wave D.5)."""

from __future__ import annotations

from typing import Any

import streamlit as st

try:
    from src.frontend.streamlit_app.utils.api_client import api_get  # type: ignore
except Exception:  # noqa: BLE001
    def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import httpx

        with httpx.Client(timeout=10) as client:
            resp = client.get(f"http://localhost:8000/api/v1{path}", params=params)
            resp.raise_for_status()
            return resp.json()


st.set_page_config(page_title="AI Cost Tracking", page_icon="💸", layout="wide")

st.title("💸 AI Cost Tracking (LangFuse)")
st.caption("Wave D.5 — единый дашборд cost-аналитики поверх LangFuse")

tabs = st.tabs(["Overview", "Top Routes", "Alerts", "LangFuse Link"])


@st.cache_data(ttl=60)
def _fetch_costs(group_by: str, top_n: int, window_hours: int) -> dict[str, Any]:
    return api_get(
        "/admin/ai-costs",
        params={"group_by": group_by, "top_n": top_n, "window_hours": window_hours},
    )


@st.cache_data(ttl=60)
def _fetch_alerts(group_by: str, window_minutes: int) -> dict[str, Any]:
    return api_get(
        "/admin/ai-costs/alerts",
        params={"group_by": group_by, "window_minutes": window_minutes},
    )


@st.cache_data(ttl=300)
def _fetch_link() -> dict[str, Any]:
    return api_get("/admin/ai-costs/link")


with tabs[0]:
    st.subheader("Общая сводка")
    col1, col2, col3 = st.columns(3)
    window = col1.selectbox("Окно (часов)", [1, 6, 24, 72, 168], index=2)
    top_n = col2.slider("Top N", min_value=5, max_value=50, value=10)
    group = col3.radio("Группировка", ["route", "tenant", "provider"], horizontal=True)

    try:
        data = _fetch_costs(group, top_n, window)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить данные: {exc}")
        data = {"backend": "error", "items": []}

    backend = data.get("backend")
    if backend == "disabled":
        st.warning(
            "LangFuse отключён (LANGFUSE_ENABLED=false). Включите для отображения "
            "данных."
        )
    elif backend == "langfuse":
        items = data.get("items") or []
        if items:
            st.dataframe(items, width=2400)
            total = sum(it.get("total_cost_usd", 0) for it in items)
            st.metric("Сумма cost_usd за окно", f"${total:,.4f}")
        else:
            st.info("Нет данных за выбранное окно.")


with tabs[1]:
    st.subheader("Top routes (1ч/24ч/7д)")
    sub = st.tabs(["1 час", "24 часа", "7 дней"])
    for tab, hours in zip(sub, [1, 24, 24 * 7]):
        with tab:
            try:
                data = _fetch_costs("route", 10, hours)
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
                continue
            st.dataframe(data.get("items") or [])


with tabs[2]:
    st.subheader("Аномалии (mean + 2σ)")
    col1, col2 = st.columns(2)
    window_min = col1.selectbox("Окно (минут)", [15, 60, 240, 1440], index=1)
    group_a = col2.radio(
        "Группировка alerts", ["route", "tenant", "provider"], horizontal=True
    )
    try:
        alerts = _fetch_alerts(group_a, window_min)
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))
        alerts = {"alerts": []}
    rows = alerts.get("alerts") or []
    if rows:
        st.dataframe(rows)
    else:
        st.info("Аномалий не обнаружено.")


with tabs[3]:
    st.subheader("LangFuse Web UI")
    try:
        link = _fetch_link()
    except Exception as exc:  # noqa: BLE001
        link = {"enabled": False, "url": None}
        st.error(str(exc))
    if link.get("enabled") and link.get("url"):
        st.link_button("Открыть LangFuse Traces", link["url"])
    else:
        st.info("LANGFUSE_DEEP_LINK_BASE/HOST не настроен.")
