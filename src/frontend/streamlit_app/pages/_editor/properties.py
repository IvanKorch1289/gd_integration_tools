"""Properties + Save panel renderer (S49 W2 TD-009 extraction).

Бывший ``with col_props:`` блок из 31_DSL_Visual_Editor.py (Canvas tab).
Right-side panel: selected step properties editor, Save/Create/Update
кнопки, Pipeline Spec preview (JSON + Python).
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.frontend.streamlit_app.pages._editor import (
    PROCESSOR_ICONS,
    VISUAL_PROCESSORS,
    sync_yaml,
)


def render_properties_panel(client: Any) -> None:
    """Render right-side panel: properties editor + save + pipeline spec.

    Args:
        client: API client instance (e.g., ``get_api_client()``) для
            ``create_dsl_route`` / ``update_dsl_route`` calls.
    """
    st.subheader("⚙️ Properties")

    if st.session_state.selected_step_index is None:
        st.info("Select a step on canvas to edit its properties.")
    else:
        idx = st.session_state.selected_step_index
        if idx >= len(st.session_state.canvas_steps):
            st.session_state.selected_step_index = None
            st.rerun()

        step = st.session_state.canvas_steps[idx]
        step_type = step["type"]
        icon = PROCESSOR_ICONS.get(step_type, "🔧")

        st.markdown(f"**{icon} {step_type}** — Step #{idx + 1}")

        available_params = VISUAL_PROCESSORS.get(step_type, [])
        current_params = step.get("params", {})

        params_changed = False
        new_params: dict[str, str] = {}
        for param in available_params:
            default_val = current_params.get(param, "")
            new_val = st.text_input(
                param,
                value=default_val,
                key=f"prop_{idx}_{param}",
                placeholder=f"value for {param}",
            )
            new_params[param] = new_val
            if new_val != default_val:
                params_changed = True

        if params_changed:
            st.session_state.canvas_steps[idx]["params"] = new_params
            sync_yaml()

        st.divider()

        c_del, c_clr = st.columns(2)
        with c_del:
            if st.button("🗑️ Delete Step", use_container_width=True):
                st.session_state.canvas_steps.pop(idx)
                st.session_state.selected_step_index = None
                sync_yaml()
                st.rerun()
        with c_clr:
            if st.button("Clear Params", use_container_width=True):
                st.session_state.canvas_steps[idx]["params"] = {
                    p: "" for p in available_params
                }
                sync_yaml()
                st.rerun()

    st.divider()
    st.subheader("💾 Save")

    col_save, col_upd = st.columns(2)
    with col_save:
        if st.button("💾 Save (Create)", use_container_width=True):
            try:
                result = client.create_dsl_route(st.session_state.yaml_output)
                st.success(f"Created: {result.get('route_id', 'OK')}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Create error: {exc}")

    with col_upd:
        route_id = st.session_state.meta_route.get("route_id", "")
        if route_id and route_id != "my.route":
            if st.button("🔄 Update", use_container_width=True):
                try:
                    client.update_dsl_route(route_id, st.session_state.yaml_output)
                    st.success(f"Updated: {route_id}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Update error: {exc}")
        else:
            st.caption("Set route_id to enable update")

    st.divider()
    st.subheader("📋 Pipeline Spec")
    try:
        from src.backend.services.dsl_portal import load_pipeline_from_yaml

        pipeline = load_pipeline_from_yaml(st.session_state.yaml_output)
        with st.expander("JSON spec"):
            st.json(pipeline.to_dict())
        with st.expander("Python code"):
            st.code(pipeline.to_python(), language="python")
    except Exception as exc:  # noqa: BLE001
        st.caption(f"Spec unavailable: {exc}")
