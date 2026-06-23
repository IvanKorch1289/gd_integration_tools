"""Sprint 13 K5 W1 — Graceful Degradation panel (S13 K2 W4 finale).

3 tabs:

* **Current Status** — текущий ``DegradationMode`` + per-component snapshot.
* **Switch Mode** (RBAC-gated) — переключение через PATCH /tech/degradation/level.
* **History** — последние 20 transitions.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Graceful Degradation", "🛡️")
st.title("🛡️ Graceful Degradation")
st.caption(
    "5-уровневая система деградации: FULL → DEGRADED → MINIMAL → MAINTENANCE → OFFLINE."
)

client = get_api_client()


_MODE_COLORS = {
    "full": "🟢 FULL",
    "read_only": "🟡 READ_ONLY",
    "degraded": "🟡 DEGRADED",
    "cache_only": "🟠 CACHE_ONLY",
    "essential_only": "🔴 ESSENTIAL_ONLY",
    "emergency": "🔴 EMERGENCY",
    "maintenance": "⚫ MAINTENANCE",
}

_MODE_OPTIONS = ["FULL", "READ_ONLY", "CACHE_ONLY", "ESSENTIAL_ONLY", "MAINTENANCE"]


tab_status, tab_switch, tab_history = st.tabs(
    ["🔍 Current Status", "⚙️ Switch Mode", "📜 History"]
)


with tab_status:
    st.subheader("Current Degradation Snapshot")

    @st.cache_data(ttl=5)
    def _load_snapshot():
        try:
            return client.get("/tech/degradation/snapshot")
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    snapshot = _load_snapshot()
    if snapshot.get("error"):
        st.error(f"Не удалось получить snapshot: {snapshot['error']}")
    else:
        mode = snapshot.get("mode", "full")
        st.metric("System Mode", _MODE_COLORS.get(mode, mode))
        components = snapshot.get("components", {})
        if components:
            st.markdown("### Components")
            for name, state in components.items():
                col1, col2, col3 = st.columns([2, 1, 1])
                col1.text(name)
                col2.metric("Available", "✅" if state.get("available") else "❌")
                col3.metric("Failures", state.get("failures", 0))


with tab_switch:
    st.subheader("Manually Switch Degradation Mode")
    st.warning(
        "⚠️ Только для OPERATOR/SUPER_ADMIN. Action audited через AdminAuditMiddleware."
    )

    new_mode = st.radio("Target Mode", options=_MODE_OPTIONS, index=0, horizontal=True)
    reason = st.text_area(
        "Reason for switch (required for compliance)",
        placeholder="например: DB primary failure, switching to READ_ONLY",
    )
    if st.button("Apply Switch", type="primary"):
        if not reason.strip():
            st.error("Reason обязателен для compliance.")
        else:
            try:
                client.patch(
                    "/tech/degradation/level",
                    json={"mode": new_mode, "reason": reason.strip()},
                )
                st.success(f"Switched to {new_mode}")
                st.cache_data.clear()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Switch failed: {exc}")


with tab_history:
    st.subheader("Recent Transitions")
    try:
        history = client.get("/tech/degradation/history")
        items = history.get("transitions", [])
        if not items:
            st.info("История пуста.")
        else:
            for t in items[-20:]:
                with st.container():
                    st.markdown(
                        f"**{t.get('timestamp_utc', '?')}** — "
                        f"`{t.get('from_mode', '?')}` → `{t.get('to_mode', '?')}` "
                        f"by **{t.get('actor', '?')}**"
                    )
                    if t.get("reason"):
                        st.caption(t["reason"])
                    st.divider()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить historic transitions: {exc}")
