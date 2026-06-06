"""Feature Flags — toggle switches."""

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page(
    'Feature Flags',
    ':triangular_flag_on_post:',
    layout='wide',
    initial_sidebar_state='expanded',
)
st.header("Feature Flags")

client = get_api_client()

try:
    flags = client.get_flags()
except Exception:
    flags = []

if flags:
    for flag in flags:
        name = flag.get("name", "unknown")
        enabled = flag.get("enabled", False)
        description = flag.get("description", "")

        col1, col2 = st.columns([4, 1])
        col1.write(f"**{name}**")
        if description:
            col1.caption(description)

        new_state = col2.toggle(name, value=enabled, key=f"flag_{name}")

        if new_state != enabled:
            success = client.toggle_flag(name, new_state)
            if success:
                st.toast(f"Flag `{name}` -> {'ON' if new_state else 'OFF'}")
            else:
                st.error(f"Не удалось переключить {name}")

    st.divider()
    st.caption(f"Всего: {len(flags)} флагов")
else:
    st.info("Нет feature flags или API недоступен.")
