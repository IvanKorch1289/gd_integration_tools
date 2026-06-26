"""Canvas (Drag-Drop) tab — extracted from pages/31_DSL_Визуальный_редактор (S173).

3-column layout: palette / canvas / properties. Uses AgGrid if available
else simple list fallback.
"""

from __future__ import annotations

import streamlit as st

from src.backend.services.dsl_portal import load_pipeline_from_yaml
from src.frontend.streamlit_app.pages._editor.constants import (
    PROCESSOR_ICONS,
    VISUAL_PROCESSORS,
)
from src.frontend.streamlit_app.pages._editor.properties import render_properties_panel
from src.frontend.streamlit_app.pages._editor.yaml_sync import sync_yaml, yaml_to_steps


def render_canvas_tab(client) -> None:
    """Render Canvas (Drag-Drop) tab: 3 columns palette/canvas/properties."""
    col_palette, col_canvas, col_props = st.columns([1, 2, 1])

    with col_palette:
        st.subheader("📦 Палитра шагов")

        palette_category = st.selectbox(
            "Категория",
            options=["all"]
            + sorted(
                set(["core", "control_flow", "routing", "transformation", "resilience"])
            ),
            index=0,
            key="canvas_category",
        )

        filtered_processors = VISUAL_PROCESSORS
        if palette_category != "all":
            filtered_processors = {
                k: v
                for k, v in VISUAL_PROCESSORS.items()
                if k in ["log", "validate", "transform", "retry"]
            }

        st.markdown("**Нажмите чтобы добавить в канвас:**")
        for proc_type, params in filtered_processors.items():
            icon = PROCESSOR_ICONS.get(proc_type, "🔧")
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"**{icon} {proc_type}**")
                    st.caption(f"Параметры: {', '.join(params) if params else 'нет'}")
                with c2:
                    if st.button("➕", key=f"add_{proc_type}", help=f"Добавить {proc_type}"):
                        st.session_state.canvas_steps.append(
                            {"type": proc_type, "params": dict.fromkeys(params, "")}
                        )
                        st.session_state.selected_step_index = (
                            len(st.session_state.canvas_steps) - 1
                        )
                        sync_yaml()
                        st.rerun()

        st.divider()
        st.subheader("💾 Загрузить маршрут")
        routes = []
        try:
            routes = client.list_dsl_routes()
        except Exception:  # noqa: BLE001
            st.caption("Не удалось загрузить список маршрутов")
        selected_route = st.selectbox(
            "Открыть существующий", ["—"] + routes, key="route_load_select"
        )
        if selected_route != "—" and st.button("Загрузить", width='stretch'):
            try:
                detail = client.get_dsl_route(selected_route)
                if detail and "yaml" in detail:
                    meta, steps = yaml_to_steps(detail["yaml"])
                    st.session_state.meta_route = meta
                    st.session_state.canvas_steps = steps
                    st.session_state.selected_step_index = None
                    sync_yaml()
                    st.success(f"Загружено: {selected_route}")
                    st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ошибка загрузки: {exc}")

        if st.button("🆕 Новый маршрут", width='stretch'):
            st.session_state.meta_route = {
                "route_id": "my.route",
                "source": "internal:my",
                "description": "New route",
            }
            st.session_state.canvas_steps = []
            st.session_state.selected_step_index = None
            sync_yaml()
            st.rerun()

    with col_canvas:
        st.subheader("🎨 Канвас — шаги Pipeline")

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
            sync_yaml()

        st.divider()

        if not st.session_state.canvas_steps:
            st.info("🖱️ Перетащите шаги из палитры или нажмите ➕ чтобы добавить. Настройте справа.")
        else:
            st.markdown(f"**Steps ({len(st.session_state.canvas_steps)}):**")

            _ag_grid_available = False
            try:
                from st_aggrid import AgGrid

                _ag_grid_available = True
            except ImportError:
                pass

            if _ag_grid_available:
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
                for i, step in enumerate(st.session_state.canvas_steps):
                    icon = PROCESSOR_ICONS.get(step["type"], "🔧")
                    params_str = ", ".join(
                        f"{k}={v}" for k, v in step["params"].items() if v
                    )
                    is_selected = st.session_state.selected_step_index == i

                    with st.container(border=is_selected):
                        c1, c2, c3, c4 = st.columns([1, 5, 1, 1])

                        if is_selected:
                            c1.markdown("👉")
                        else:
                            if c1.button(f"#{i + 1}", key=f"sel_{i}", help="Выбрать"):
                                st.session_state.selected_step_index = i
                                st.rerun()

                        with c2:
                            st.markdown(f"**{icon} {step['type']}**")
                            if params_str:
                                st.caption(f"_{params_str}_")

                        col_up, col_down, col_del = c3, c4, st.columns(2)[1]
                        if col_up.button(
                            "⬆️", key=f"up_{i}", help="Переместить вверх", disabled=i == 0
                        ):
                            (
                                st.session_state.canvas_steps[i - 1],
                                st.session_state.canvas_steps[i],
                            ) = (
                                st.session_state.canvas_steps[i],
                                st.session_state.canvas_steps[i - 1],
                            )
                            sync_yaml()
                            st.rerun()
                        if col_down.button(
                            "⬇️",
                            key=f"down_{i}",
                            help="Переместить вниз",
                            disabled=i == len(st.session_state.canvas_steps) - 1,
                        ):
                            (
                                st.session_state.canvas_steps[i + 1],
                                st.session_state.canvas_steps[i],
                            ) = (
                                st.session_state.canvas_steps[i],
                                st.session_state.canvas_steps[i + 1],
                            )
                            sync_yaml()
                            st.rerun()
                        if col_del.button("🗑️", key=f"del_{i}", help="Удалить"):
                            st.session_state.canvas_steps.pop(i)
                            if st.session_state.selected_step_index == i:
                                st.session_state.selected_step_index = None
                            elif (
                                st.session_state.selected_step_index
                                and st.session_state.selected_step_index > i
                            ):
                                st.session_state.selected_step_index -= 1
                            sync_yaml()
                            st.rerun()

        st.divider()
        st.subheader("📄 Превью YAML")
        yaml_preview = st.text_area(
            "YAML",
            value=st.session_state.yaml_output,
            height=200,
            key="yaml_preview_area",
            label_visibility="collapsed",
        )
        if yaml_preview != st.session_state.yaml_output:
            st.session_state.yaml_output = yaml_preview

        col_val, col_down = st.columns(2)
        with col_val:
            if st.button("✅ Валидировать", width='stretch'):
                try:
                    load_pipeline_from_yaml(st.session_state.yaml_output)
                    st.success("✅ YAML валиден!")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"❌ Невалидно: {exc}")

        with col_down:
            yaml_bytes = st.session_state.yaml_output.encode("utf-8")
            st.download_button(
                "📥 Скачать YAML",
                data=yaml_bytes,
                file_name=f"{st.session_state.meta_route.get('route_id', 'route')}.yaml",
                mime="text/yaml",
                width='stretch',
            )

    with col_props:
        render_properties_panel(client)
