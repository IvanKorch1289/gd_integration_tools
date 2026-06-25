"""Sprint 13 K5 W2 — Resilience Profile Editor (S13 K2 W5).

Per-tenant tune CB/RL/Retry/Bulkhead. Использует
``/api/v1/admin/resilience-profiles`` REST API.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page
from src.frontend.streamlit_app.shared.filters import slider_filter  # S45 W2 (TD-008)

setup_page("Редактор профилей устойчивости", "⚙️")
st.title("⚙️ Редактор профилей устойчивости")
st.caption("Тенантный override: Circuit Breaker / Rate Limit / Retry / Bulkhead.")

client = get_api_client()


with st.sidebar:
    tenant_id = st.text_input("ID тенанта (пусто = глобально)", value="")

tab_list, tab_edit, tab_compare = st.tabs(
    ["📋 Список профилей", "✏️ Редактировать профиль", "🔍 Сравнить"]
)


with tab_list:
    st.subheader("Все профили устойчивости")
    try:
        params = {"tenant_id": tenant_id} if tenant_id else {}
        data = client.get("/api/v1/admin/resilience-profiles", params=params)
        profiles = data.get("profiles", [])
        if not profiles:
            st.info("Нет зарегистрированных профилей.")
        for prof in profiles:
            with st.expander(f"📦 {prof.get('name', '?')}"):
                st.json(prof)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить профили: {exc}")


with tab_edit:
    st.subheader("Создать / Редактировать профиль")
    name = st.text_input("Имя профиля", placeholder="например: external_api_default")

    st.markdown("### Retry policy")
    col1, col2, col3 = st.columns(3)
    max_attempts = col1.slider("Макс. попыток", 1, 10, 3)
    base_delay_ms = col2.slider("Базовая задержка (мс)", 10, 5000, 100)
    exp_base = col3.slider("База экспоненты", 1.1, 3.0, 2.0)

    st.markdown("### Circuit Breaker")
    col1, col2 = st.columns(2)
    failure_threshold = col1.slider("Порог ошибок", 3, 50, 5)
    recovery_timeout_s = col2.slider("Таймаут восстановления (с)", 10, 3600, 30)

    st.markdown("### Rate Limit (опционально)")
    enable_rl = st.checkbox("Включить rate limit")
    rl_rps = slider_filter(
        "RPS", min_value=1, max_value=10000, default=100, key="rl_rps"
    )
    rl_burst = slider_filter(
        "Burst", min_value=1, max_value=100, default=20, key="rl_burst"
    )

    st.markdown("### Bulkhead (опционально)")
    enable_bh = st.checkbox("Включить bulkhead")
    bh_high = slider_filter(
        "High watermark", min_value=10, max_value=1000, default=100, key="bh_high"
    )
    bh_low = slider_filter(
        "Low watermark", min_value=5, max_value=500, default=50, key="bh_low"
    )

    if st.button("💾 Сохранить профиль", type="primary"):
        if not name.strip():
            st.error("Имя профиля обязательно.")
        else:
            payload = {
                "retry": {
                    "max_attempts": max_attempts,
                    "base_delay_ms": base_delay_ms,
                    "max_delay_ms": 5000,
                    "exp_base": exp_base,
                    "jitter": 0.1,
                },
                "circuit_breaker": {
                    "failure_threshold": failure_threshold,
                    "recovery_timeout_s": recovery_timeout_s,
                    "half_open_max_calls": 3,
                },
                "rate_limit": (
                    {"rps": rl_rps, "burst": rl_burst} if enable_rl else None
                ),
                "bulkhead": (
                    {"high_watermark": bh_high, "low_watermark": bh_low}
                    if enable_bh
                    else None
                ),
            }
            try:
                params = {"tenant_id": tenant_id} if tenant_id else {}
                client.put(
                    f"/api/v1/admin/resilience-profiles/{name}",
                    json=payload,
                    params=params,
                )
                st.success(f"Профиль '{name}' сохранён.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Сохранение не удалось: {exc}")


with tab_compare:
    st.subheader("Сравнение глобального и тенантного override")
    compare_name = st.text_input("Имя профиля для сравнения")
    if compare_name:
        try:
            global_p = client.get(f"/api/v1/admin/resilience-profiles/{compare_name}")
            tenant_p = (
                client.get(
                    f"/api/v1/admin/resilience-profiles/{compare_name}",
                    params={"tenant_id": tenant_id},
                )
                if tenant_id
                else None
            )
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Глобальный**")
                st.json(global_p)
            with col2:
                st.markdown("**Тенант**" if tenant_id else "**(нет тенанта)**")
                if tenant_p:
                    st.json(tenant_p)
                else:
                    st.info("Tenant override отсутствует.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Сравнение не удалось: {exc}")
