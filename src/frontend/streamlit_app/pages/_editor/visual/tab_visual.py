"""Visual tab — extracted from pages/31_DSL_Визуальный_редактор (S173).

Drag-drop reorder + metadata + add processor + step list.
"""

from __future__ import annotations

import json as _json

import streamlit as st

from src.frontend.streamlit_app.pages._editor.canvas import render_drag_drop_pipeline
from src.frontend.streamlit_app.pages._editor.constants import VISUAL_PROCESSORS
from src.frontend.streamlit_app.pages._editor.history import push_history
from src.frontend.streamlit_app.pages._editor.yaml_sync import (
    build_yaml_from_steps,
    yaml_to_steps,
)


def render_visual_tab() -> None:
    """Render Visual tab: drag-drop reorder + metadata + step list."""
    # Handle reorder from drag-drop via query params
    query_params = st.query_params
    if "reorder" in query_params:
        try:
            reordered_steps = _json.loads(query_params["reorder"])
            if isinstance(reordered_steps, list):
                meta, current_steps = yaml_to_steps(st.session_state.yaml)
                if len(reordered_steps) == len(current_steps):
                    st.session_state.yaml = build_yaml_from_steps(meta, reordered_steps)
                    push_history()
        except Exception:  # noqa: BLE001,S110
            pass
        # Clear the query param
        query_params.clear()
        st.rerun()

    meta, steps = yaml_to_steps(st.session_state.yaml)

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Метаданные")
        new_route_id = st.text_input(
            "route_id", value=meta.get("route_id", ""), key="vis_route_id"
        )
        new_source = st.text_input(
            "source", value=meta.get("source", ""), key="vis_source"
        )
        new_desc = st.text_input(
            "description", value=meta.get("description", "") or "", key="vis_desc"
        )

        st.divider()
        st.subheader("Добавить процессор")
        proc_type = st.selectbox(
            "Тип", list(VISUAL_PROCESSORS.keys()), key="vis_proc_type"
        )
        new_params: dict[str, str] = {}
        for p in VISUAL_PROCESSORS[proc_type]:
            new_params[p] = st.text_input(
                p, key=f"vis_p_{proc_type}_{p}", placeholder=f"значение для {p}"
            )

        if st.button("+ Добавить процессор", width='stretch'):
            params_clean = {k: v for k, v in new_params.items() if v != ""}
            steps.append({"type": proc_type, "params": params_clean})
            st.session_state.yaml = build_yaml_from_steps(
                {
                    "route_id": new_route_id,
                    "source": new_source,
                    "description": new_desc,
                },
                steps,
            )
            push_history()
            st.rerun()

    with col_right:
        st.subheader("🔗 Pipeline (перетащите для изменения порядка)")
        st.caption("Перетащите процессоры для изменения порядка")

        # Render drag-drop pipeline
        render_drag_drop_pipeline(steps, meta)

        st.divider()
        st.subheader("📝 Список процессоров")

        if not steps:
            st.info("Пусто. Добавьте процессор слева или перетащите из палитры.")
        for i, step in enumerate(steps):
            c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
            params_str = ", ".join(f"{k}={v}" for k, v in step["params"].items())
            c1.write(f"**{i + 1}. {step['type']}** ({params_str})")
            if c2.button("↑", key=f"up_{i}", disabled=i == 0):
                steps[i - 1], steps[i] = steps[i], steps[i - 1]
                st.session_state.yaml = build_yaml_from_steps(
                    {
                        "route_id": new_route_id,
                        "source": new_source,
                        "description": new_desc,
                    },
                    steps,
                )
                push_history()
                st.rerun()
            if c3.button("↓", key=f"down_{i}", disabled=i == len(steps) - 1):
                steps[i], steps[i + 1] = steps[i + 1], steps[i]
                st.session_state.yaml = build_yaml_from_steps(
                    {
                        "route_id": new_route_id,
                        "source": new_source,
                        "description": new_desc,
                    },
                    steps,
                )
                push_history()
                st.rerun()
            if c4.button("✕", key=f"del_{i}"):
                steps.pop(i)
                st.session_state.yaml = build_yaml_from_steps(
                    {
                        "route_id": new_route_id,
                        "source": new_source,
                        "description": new_desc,
                    },
                    steps,
                )
                push_history()
                st.rerun()

        rebuilt = build_yaml_from_steps(
            {"route_id": new_route_id, "source": new_source, "description": new_desc},
            steps,
        )
        if rebuilt != st.session_state.yaml:
            st.session_state.yaml = rebuilt
