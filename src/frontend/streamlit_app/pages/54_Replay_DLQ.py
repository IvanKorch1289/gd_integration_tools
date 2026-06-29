"""DLQ Replay — тонкий shim для render_dlq_replay() (S173 refactor).

Helpers и UI logic вынесены в ``_groups/replay/``.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.pages._groups.replay.render import render_dlq_replay
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page()
st.header("Воспроизведение DLQ")

# Feature-flag guard
try:
    from src.backend.core.frontend_facade import (
        feature_flags as _ff,  # noqa: E402, F401
    )

    _flag_enabled: bool = bool(getattr(_ff, "dlq_unified_enabled", False))
except Exception:  # noqa: BLE001
    st.error("Не удалось выполнить запрос — проверьте подключение к серверу")
    _flag_enabled = False

with st.sidebar:
    st.subheader("Настройки")
    st.toggle(
        "UI воспроизведения DLQ",
        value=_flag_enabled,
        help="feature_flags.dlq_unified_enabled (FEATURE_DLQ_UNIFIED_ENABLED)",
        disabled=True,
    )
    st.caption(
        "Для включения установите `FEATURE_DLQ_UNIFIED_ENABLED=true` "
        "или обновите `features.yaml`."
    )

if not _flag_enabled:
    st.warning(
        "DLQ Replay UI отключён (feature_flag: `dlq_unified_enabled = false`). "
        "Установите `FEATURE_DLQ_UNIFIED_ENABLED=true` для активации."
    )
    st.stop()

render_dlq_replay()

related_pages_footer("54_Replay_DLQ")
