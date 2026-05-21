"""Sprint 13 K5 W2 — Resilience Profile Editor (S13 K2 W5).

Per-tenant tune CB/RL/Retry/Bulkhead. Использует
``/api/v1/admin/resilience-profiles`` REST API.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Resilience Profile Editor", page_icon="⚙️", layout="wide")
st.title("⚙️ Resilience Profile Editor")
st.caption("Sprint 13 K5 W2 — per-tenant override CB/RL/Retry/Bulkhead.")

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
    rl_rps = st.slider("RPS", 1, 10000, 100, disabled=not enable_rl)
    rl_burst = st.slider("Burst", 1, 100, 20, disabled=not enable_rl)

    st.markdown("### Bulkhead (optional)")
    enable_bh = st.checkbox("Enable bulkhead")
    bh_high = st.slider("High watermark", 10, 1000, 100, disabled=not enable_bh)
    bh_low = st.slider("Low watermark", 5, 500, 50, disabled=not enable_bh)

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
