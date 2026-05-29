"""Sprint 19 K3 W5 — DSL Visual Editor Finale.

Drag-drop route editor with three-panel layout:
- Left: step palette (processor types)
- Center: canvas (ordered pipeline steps)
- Right: properties panel (step configuration)

Export to YAML. Feature-flag: ``dsl_visual_editor_enabled`` (default-OFF).

Uses st-ag-grid for drag-drop reordering when available, falls back to
button-based reordering when not.
"""

from __future__ import annotations

import streamlit as st
import yaml as _yaml

from src.backend.services.dsl_portal import load_pipeline_from_yaml  # noqa: E402
from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

# ─── Feature-flag check ──────────────────────────────────────────────────────

try:
    from src.backend.core.config.features import feature_flags as _ff

    _FLAG_ENABLED = _ff.dsl_visual_editor_enabled
except Exception:  # noqa: BLE001 — graceful degradation
    _FLAG_ENABLED = False

st.set_page_config(page_title="DSL Visual Editor (Drag-Drop)", layout="wide")

# ─── Sidebar: feature-flag toggle ───────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Settings")
    flag_override = st.toggle(
        "dsl_visual_editor_enabled",
        value=_FLAG_ENABLED,
        help=(
            "Sprint 19 K3 W5. Toggles the drag-drop DSL Visual Editor. "
            "Production value controlled via FEATURE_DSL_VISUAL_EDITOR_ENABLED env."
        ),
    )

st.header("🔀 DSL Visual Editor — Drag-Drop Route Builder")
st.caption(
    "Sprint 19 K3 W5 Finale. "
    "Drag steps from palette → canvas. Configure properties on right. Export YAML."
)

if not flag_override:
    st.warning(
        "DSL Visual Editor отключён (`dsl_visual_editor_enabled = false`). "
        "Включите toggle в боковой панели для работы (сессионный override).",
        icon="⚠️",
    )
    st.stop()

# ─── Processor palette ────────────────────────────────────────────────────────

VISUAL_PROCESSORS: dict[str, list[str]] = {
    "log": ["level", "message"],
    "validate": ["schema"],
    "transform": ["expression"],
    "dispatch_action": ["action"],
    "retry": ["max_attempts", "delay"],
    "redirect": ["mode", "status_code", "target_url", "url_source", "source_key"],
    "windowed_dedup": ["key_from", "window_seconds", "mode"],
    "windowed_collect": [
        "key_from",
        "window_seconds",
        "dedup_by",
        "dedup_mode",
        "inject_as",
    ],
    "multicast_routes": ["route_ids", "strategy", "on_error", "timeout"],
    "express_send": ["bot", "chat_id_from", "body_from"],
    "express_reply": ["bot", "body_from"],
    "notify": ["channel", "to", "template"],
}

PROCESSOR_ICONS: dict[str, str] = {
    "log": "📋",
    "validate": "✅",
    "transform": "🔄",
    "dispatch_action": "🎯",
    "retry": "🔁",
    "redirect": "↗️",
    "windowed_dedup": "🗂️",
    "windowed_collect": "📥",
    "multicast_routes": "📡",
    "express_send": "📨",
    "express_reply": "📩",
    "notify": "🔔",
}

# ─── Session state ────────────────────────────────────────────────────────────

if "canvas_steps" not in st.session_state:
    st.session_state.canvas_steps = []  # list[dict] — {"type": ..., "params": {...}}

if "selected_step_index" not in st.session_state:
    st.session_state.selected_step_index = None

if "yaml_output" not in st.session_state:
    st.session_state.yaml_output = ""

if "meta_route" not in st.session_state:
    st.session_state.meta_route = {
        "route_id": "my.route",
        "source": "internal:my",
        "description": "New route",
    }

client = get_api_client()


def _build_yaml_from_steps(meta: dict, steps: list[dict]) -> str:
    """Serialize meta + steps to YAML string."""
    out: dict = {"route_id": meta.get("route_id") or "my.route"}
    if meta.get("source"):
        out["source"] = meta["source"]
    if meta.get("description"):
        out["description"] = meta["description"]
    if steps:
        out["processors"] = [{s["type"]: s.get("params") or {}} for s in steps]
    return _yaml.dump(out, allow_unicode=True, sort_keys=False)


def _yaml_to_steps(yaml_str: str) -> tuple[dict, list[dict]]:
    """Parse YAML string to meta dict and steps list."""
    try:
        data = _yaml.safe_load(yaml_str) or {}
    except _yaml.YAMLError:
        return {}, []
    if not isinstance(data, dict):
        return {}, []
    meta = {
        "route_id": data.get("route_id", ""),
        "source": data.get("source", ""),
        "description": data.get("description", ""),
    }
    raw = data.get("processors", []) or []
    steps: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            steps.append({"type": item, "params": {}})
        elif isinstance(item, dict) and len(item) == 1:
            name = next(iter(item))
            params = item[name] if isinstance(item[name], dict) else {}
            steps.append({"type": name, "params": params})
    return meta, steps


def _sync_yaml():
    """Re-serialize session state to YAML."""
    st.session_state.yaml_output = _build_yaml_from_steps(
        st.session_state.meta_route, st.session_state.canvas_steps
    )


# ─── Three-column layout ──────────────────────────────────────────────────────

col_palette, col_canvas, col_props = st.columns([1, 2, 1])

# ════════════════════════════════════════════════════════════════════════════
# LEFT: Step Palette
# ════════════════════════════════════════════════════════════════════════════

with col_palette:
    st.subheader("📦 Step Palette")

    palette_category = st.selectbox(
        "Category",
        options=["all"]
        + sorted(set("core control_flow routing transformation resilience".split())),
        index=0,
    )

    filtered_processors = VISUAL_PROCESSORS
    if palette_category != "all":
        # Simple filter - in production would use namespace tags
        filtered_processors = {
            k: v
            for k, v in VISUAL_PROCESSORS.items()
            if k in ["log", "validate", "transform", "retry"]
        }

    st.markdown("**Click to add to canvas:**")
    for proc_type, params in filtered_processors.items():
        icon = PROCESSOR_ICONS.get(proc_type, "🔧")
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{icon} {proc_type}**")
                st.caption(f"Params: {', '.join(params) if params else 'none'}")
            with c2:
                if st.button("➕", key=f"add_{proc_type}", help=f"Add {proc_type}"):
                    st.session_state.canvas_steps.append(
                        {"type": proc_type, "params": {p: "" for p in params}}
                    )
                    st.session_state.selected_step_index = (
                        len(st.session_state.canvas_steps) - 1
                    )
                    _sync_yaml()
                    st.rerun()

    st.divider()
    st.subheader("💾 Load Route")
    routes = []
    try:
        routes = client.list_dsl_routes()
    except Exception:  # noqa: BLE001
        st.caption("Could not load routes list")
    selected_route = st.selectbox(
        "Open existing", ["—"] + routes, key="route_load_select"
    )
    if selected_route != "—" and st.button("Load", use_container_width=True):
        try:
            detail = client.get_dsl_route(selected_route)
            if detail and "yaml" in detail:
                meta, steps = _yaml_to_steps(detail["yaml"])
                st.session_state.meta_route = meta
                st.session_state.canvas_steps = steps
                st.session_state.selected_step_index = None
                _sync_yaml()
                st.success(f"Loaded: {selected_route}")
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Load error: {exc}")

    if st.button("🆕 New Route", use_container_width=True):
        st.session_state.meta_route = {
            "route_id": "my.route",
            "source": "internal:my",
            "description": "New route",
        }
        st.session_state.canvas_steps = []
        st.session_state.selected_step_index = None
        _sync_yaml()
        st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# CENTER: Canvas
# ════════════════════════════════════════════════════════════════════════════

with col_canvas:
    st.subheader("🎨 Canvas — Pipeline Steps")

    # Meta fields at top
    m1, m2 = st.columns(2)
    with m1:
        new_route_id = st.text_input(
            "route_id",
            value=st.session_state.meta_route.get("route_id", ""),
            key="canvas_route_id",
        )
    with m2:
        new_source = st.text_input(
            "source",
            value=st.session_state.meta_route.get("source", ""),
            key="canvas_source",
        )
    new_desc = st.text_input(
        "description",
        value=st.session_state.meta_route.get("description", ""),
        key="canvas_desc",
    )

    # Update meta if changed
    if (
        new_route_id != st.session_state.meta_route.get("route_id")
        or new_source != st.session_state.meta_route.get("source")
        or new_desc != st.session_state.meta_route.get("description")
    ):
        st.session_state.meta_route = {
            "route_id": new_route_id,
            "source": new_source,
            "description": new_desc,
        }
        _sync_yaml()

    st.divider()

    if not st.session_state.canvas_steps:
        st.info("🖱️ Drag steps from palette or click ➕ to add. Configure on right.")
    else:
        st.markdown(f"**Steps ({len(st.session_state.canvas_steps)}):**")

        # Try to use st-ag-grid for drag-drop if available
        _ag_grid_available = False
        try:
            from st_aggrid import AgGrid

            _ag_grid_available = True
        except ImportError:
            pass

        if _ag_grid_available:
            # AgGrid-based drag-drop reordering
            grid_data = []
            for i, step in enumerate(st.session_state.canvas_steps):
                params_str = ", ".join(
                    f"{k}={v}" for k, v in step["params"].items() if v
                )
                grid_data.append(
                    {
                        "index": i,
                        "step": step["type"],
                        "params": params_str,
                        "icon": PROCESSOR_ICONS.get(step["type"], "🔧"),
                    }
                )

            grid_options = {
                "rowSelection": "single",
                "animateRows": True,
                "enableRangeSelection": False,
            }
            grid_response = AgGrid(
                data=grid_data,
                grid_options=grid_options,
                height=400,
                key="canvas_grid",
                update_on=["ROW_ORDER_CHANGED"],
            )

            if grid_response and hasattr(grid_response, "selected_rows"):
                selected = grid_response.selected_rows
                if selected:
                    idx = selected[0].get("index")
                    if idx is not None:
                        st.session_state.selected_step_index = idx
        else:
            # Fallback: button-based reordering
            for i, step in enumerate(st.session_state.canvas_steps):
                icon = PROCESSOR_ICONS.get(step["type"], "🔧")
                params_str = ", ".join(
                    f"{k}={v}" for k, v in step["params"].items() if v
                )
                is_selected = st.session_state.selected_step_index == i

                with st.container(border=is_selected):
                    c1, c2, c3, c4 = st.columns([1, 5, 1, 1])

                    # Selection indicator
                    if is_selected:
                        c1.markdown("👉")
                    else:
                        if c1.button(f"#{i + 1}", key=f"sel_{i}", help="Select"):
                            st.session_state.selected_step_index = i
                            st.rerun()

                    # Step info
                    with c2:
                        st.markdown(f"**{icon} {step['type']}**")
                        if params_str:
                            st.caption(f"_{params_str}_")

                    # Reorder buttons
                    col_up, col_down, col_del = c3, c4, st.columns(2)[1]
                    if col_up.button(
                        "⬆️", key=f"up_{i}", help="Move up", disabled=i == 0
                    ):
                        (
                            st.session_state.canvas_steps[i - 1],
                            st.session_state.canvas_steps[i],
                        ) = (
                            st.session_state.canvas_steps[i],
                            st.session_state.canvas_steps[i - 1],
                        )
                        _sync_yaml()
                        st.rerun()
                    if col_down.button(
                        "⬇️",
                        key=f"down_{i}",
                        help="Move down",
                        disabled=i == len(st.session_state.canvas_steps) - 1,
                    ):
                        (
                            st.session_state.canvas_steps[i + 1],
                            st.session_state.canvas_steps[i],
                        ) = (
                            st.session_state.canvas_steps[i],
                            st.session_state.canvas_steps[i + 1],
                        )
                        _sync_yaml()
                        st.rerun()
                    if col_del.button("🗑️", key=f"del_{i}", help="Delete"):
                        st.session_state.canvas_steps.pop(i)
                        if st.session_state.selected_step_index == i:
                            st.session_state.selected_step_index = None
                        elif (
                            st.session_state.selected_step_index
                            and st.session_state.selected_step_index > i
                        ):
                            st.session_state.selected_step_index -= 1
                        _sync_yaml()
                        st.rerun()

    st.divider()
    st.subheader("📄 YAML Preview")
    yaml_preview = st.text_area(
        "YAML",
        value=st.session_state.yaml_output,
        height=200,
        key="yaml_preview_area",
        label_visibility="collapsed",
    )
    if yaml_preview != st.session_state.yaml_output:
        st.session_state.yaml_output = yaml_preview

    # Validate button
    col_val, col_down = st.columns(2)
    with col_val:
        if st.button("✅ Validate", use_container_width=True):
            try:
                load_pipeline_from_yaml(st.session_state.yaml_output)
                st.success("✅ YAML valid!")
            except Exception as exc:  # noqa: BLE001
                st.error(f"❌ Invalid: {exc}")

    with col_down:
        yaml_bytes = st.session_state.yaml_output.encode("utf-8")
        st.download_button(
            "📥 Download YAML",
            data=yaml_bytes,
            file_name=f"{st.session_state.meta_route.get('route_id', 'route')}.yaml",
            mime="text/yaml",
            use_container_width=True,
        )

# ════════════════════════════════════════════════════════════════════════════
# RIGHT: Properties Panel
# ════════════════════════════════════════════════════════════════════════════

with col_props:
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
        new_params = {}
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
            _sync_yaml()

        st.divider()

        # Step actions
        c_del, c_clr = st.columns(2)
        with c_del:
            if st.button("🗑️ Delete Step", use_container_width=True):
                st.session_state.canvas_steps.pop(idx)
                st.session_state.selected_step_index = None
                _sync_yaml()
                st.rerun()
        with c_clr:
            if st.button("Clear Params", use_container_width=True):
                st.session_state.canvas_steps[idx]["params"] = {
                    p: "" for p in available_params
                }
                _sync_yaml()
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

    # JSON spec preview
    st.divider()
    st.subheader("📋 Pipeline Spec")
    try:
        pipeline = load_pipeline_from_yaml(st.session_state.yaml_output)
        with st.expander("JSON spec"):
            st.json(pipeline.to_dict())
        with st.expander("Python code"):
            st.code(pipeline.to_python(), language="python")
    except Exception as exc:  # noqa: BLE001
        st.caption(f"Spec unavailable: {exc}")
