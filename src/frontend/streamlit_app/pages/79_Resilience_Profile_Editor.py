"""Sprint 13 K5 W2 — Resilience Profile Editor (S13 K2 W5).

Per-tenant tune CB/RL/Retry/Bulkhead. Использует
``/api/v1/admin/resilience-profiles`` REST API.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page
from src.frontend.streamlit_app.shared.filters import slider_filter  # S45 W2 (TD-008)

setup_page("Resilience Profile Editor", "⚙️")
st.title("⚙️ Resilience Profile Editor")
st.caption("Per-tenant override: Circuit Breaker / Rate Limit / Retry / Bulkhead.")

client = get_api_client()


with st.sidebar:
    tenant_id = st.text_input("Tenant ID (empty = global)", value="")

tab_list, tab_edit, tab_compare = st.tabs(
    ["📋 List Profiles", "✏️ Edit Profile", "🔍 Compare"]
)


with tab_list:
    st.subheader("All Resilience Profiles")
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
    st.subheader("Create / Edit Profile")
    name = st.text_input("Profile name", placeholder="например: external_api_default")

    st.markdown("### Retry policy")
    col1, col2, col3 = st.columns(3)
    max_attempts = col1.slider("Max attempts", 1, 10, 3)
    base_delay_ms = col2.slider("Base delay (ms)", 10, 5000, 100)
    exp_base = col3.slider("Exp base", 1.1, 3.0, 2.0)

    st.markdown("### Circuit Breaker")
    col1, col2 = st.columns(2)
    failure_threshold = col1.slider("Failure threshold", 3, 50, 5)
    recovery_timeout_s = col2.slider("Recovery timeout (s)", 10, 3600, 30)

    st.markdown("### Rate Limit (optional)")
    enable_rl = st.checkbox("Enable rate limit")
    rl_rps = slider_filter(
        "RPS", min_value=1, max_value=10000, default=100, key="rl_rps"
    )
    rl_burst = slider_filter(
        "Burst", min_value=1, max_value=100, default=20, key="rl_burst"
    )

    st.markdown("### Bulkhead (optional)")
    enable_bh = st.checkbox("Enable bulkhead")
    bh_high = slider_filter(
        "High watermark", min_value=10, max_value=1000, default=100, key="bh_high"
    )
    bh_low = slider_filter(
        "Low watermark", min_value=5, max_value=500, default=50, key="bh_low"
    )

    if st.button("💾 Save Profile", type="primary"):
        if not name.strip():
            st.error("Profile name is required.")
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
                st.success(f"Profile '{name}' saved.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Save failed: {exc}")


with tab_compare:
    st.subheader("Compare global vs tenant override")
    compare_name = st.text_input("Profile name to compare")
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
                st.markdown("**Global**")
                st.json(global_p)
            with col2:
                st.markdown("**Tenant**" if tenant_id else "**(no tenant)**")
                if tenant_p:
                    st.json(tenant_p)
                else:
                    st.info("Tenant override отсутствует.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Compare failed: {exc}")
