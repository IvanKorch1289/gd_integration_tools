"""Python tab — extracted from pages/31_DSL_Визуальный_редактор (S173).

Pipeline → Python source code preview (round-trip).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.pages._editor.yaml_sync import (
    try_load,
)


def render_python_tab() -> None:
    """Render Python tab: YAML → Python source code."""
    pipeline, err = try_load(st.session_state.yaml)
    if err:
        st.error(f"Невалидный YAML: {err}")
        st.caption("Исправьте YAML — Python-код сгенерируется автоматически.")
    else:
        st.code(pipeline.to_python(), language="python")
        st.caption(
            "Round-trip: этот код, выполненный в Python, создаёт идентичный "
            "Pipeline через RouteBuilder."
        )