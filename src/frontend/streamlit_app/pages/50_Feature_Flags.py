"""Feature Flags — toggle switches."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(
    page_title="Feature Flags", page_icon=":triangular_flag_on_post:", layout="wide"
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
