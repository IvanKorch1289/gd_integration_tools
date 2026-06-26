"""DSL Visual Editor — конструктор маршрутов с round-trip Visual ↔ YAML ↔ Python.

Wave 3.8 (bidirectional YAML ↔ Python). Три синхронизированные вкладки:

    * **Visual** — пошаговый сборщик процессоров (form-based UI).
    * **YAML** — редактируемый YAML-исходник с server-side валидацией.
    * **Python** — read-only код, генерируется из текущего YAML через
      :meth:`Pipeline.to_python`.

Источник правды — поле ``yaml`` в ``st.session_state``. Visual-вкладка
перестраивает YAML из шагов; YAML-вкладка обновляет YAML напрямую.
Python и preview-spec вычисляются on-demand через локальный
``load_pipeline_from_yaml``.

Сохранение и загрузка — через REST API ``/api/v1/admin/dsl-routes``
(:mod:`src.entrypoints.api.v1.endpoints.dsl_routes`).
"""

# NOTE (S93 W2-C11): PYTHONPATH=$(pwd) устанавливается manage.py run-frontend.
# Прямой запуск `streamlit run` без PYTHONPATH упадёт с ImportError.

from __future__ import annotations

import streamlit as st

from src.backend.services.dsl_portal import load_pipeline_from_yaml
from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.pages._editor import (
    PROCESSOR_ICONS,
    VISUAL_PROCESSORS,
    build_yaml_from_steps,
    can_redo,
    can_undo,
    default_yaml,
    init_history,
    push_history,
    redo,
    sync_yaml,
    try_load,
    undo,
    yaml_to_steps,
)
from src.frontend.streamlit_app.pages._editor.canvas import render_drag_drop_pipeline
from src.frontend.streamlit_app.pages._editor.palette import render_step_palette
from src.frontend.streamlit_app.pages._editor.properties import render_properties_panel
from src.frontend.streamlit_app.pages._editor.workflow_diff import render_workflow_diff
from src.frontend.streamlit_app.shared.components import require_auth, setup_page, related_pages_footer

setup_page()
require_auth(label="write action")
st.header("DSL Визуальный редактор")
st.caption(
    "Round-trip Visual ↔ YAML ↔ Python через RouteBuilder. "
    "Сохранение в YAMLStore через Admin API."
)


# ─── Default yaml + session state init (BEFORE history!) ─────────────────
# Порядок важен: init_history() читает st.session_state.yaml, поэтому
# сначала инициализируем yaml, потом — history stack.
# P0 баг был: history init шло до yaml init → AttributeError на первой
# загрузке. (S77 W3 followup roe-agent review).
if "yaml" not in st.session_state:
    st.session_state.yaml = default_yaml()

# ─── Undo/redo history init (extracted в _editor/history.py) ──────────────
init_history()

if "last_load_route" not in st.session_state:
    st.session_state.last_load_route = None

# ─── Canvas session state (from 40_dsl_visual_editor) ────────────────────
if "canvas_steps" not in st.session_state:
    st.session_state.canvas_steps = []

if "selected_step_index" not in st.session_state:
    st.session_state.selected_step_index = None

if "yaml_output" not in st.session_state:
    st.session_state.yaml_output = ""

if "meta_route" not in st.session_state:
    st.session_state.meta_route = {
        "route_id": "my.route",
        "source": "internal:my",
        "description": "Новый маршрут",
    }


client = get_api_client()


# ──────────────────────── Render Step Palette in Sidebar ─────────────────────
render_step_palette()


# Sidebar — extracted to _editor/sidebar_panel.py
with st.sidebar:
    render_editor_sidebar(client)



tab_visual, tab_yaml, tab_python, tab_diff, tab_canvas = st.tabs(
    ["Visual", "YAML", "Python", "Сравнение workflow", "Канвас (Drag-Drop)"]
)


with tab_visual:
    # Handle reorder from drag-drop via query params
    import json as _json

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


with tab_yaml:
    new_yaml = st.text_area(
        "YAML",
        value=st.session_state.yaml,
        height=420,
        key="yaml_editor",
        help="Редактируется напрямую. Visual-вкладка перестраивается из этого YAML.",
    )
    if new_yaml != st.session_state.yaml:
        st.session_state.yaml = new_yaml
        push_history()

    cols = st.columns([1, 1, 4])
    if cols[0].button("Валидировать (сервер)", width='stretch'):
        result = client.validate_dsl_route(st.session_state.yaml)
        if result.get("valid"):
            st.success(
                f"OK · route_id={result.get('route_id')} · "
                f"процессоров: {result.get('processors_count', 0)}"
            )
        else:
            st.error(f"Ошибка: {result.get('error')}")

    if (
        cols[1].button("Сравнить с сохранённой версией", width='stretch')
        and st.session_state.last_load_route
    ):
        diff = client.diff_dsl_route(
            st.session_state.last_load_route, st.session_state.yaml
        )
        if diff and diff.get("diff"):
            st.code(diff["diff"], language="diff")
        else:
            st.info("Изменений нет.")

    pipeline, err = try_load(st.session_state.yaml)
    if err:
        st.error(f"Локальная валидация: {err}")
    else:
        with st.expander("JSON спецификация"):
            st.json(pipeline.to_dict())


with tab_python:
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


# ──────────────────────── Sprint 12 K3 W1: Workflow Diff ─────────────────
with tab_diff:
    render_workflow_diff()

# ═══════════════════════════════════════════════════════════════════════════════
# Canvas (Drag-Drop) tab — adapted from 40_dsl_visual_editor.py
# ═══════════════════════════════════════════════════════════════════════════════

with tab_canvas:
    col_palette, col_canvas, col_props = st.columns([1, 2, 1])

    with col_palette:
        st.subheader("📦 Палитра шагов")

        palette_category = st.selectbox(
            "Категория",
            options=["all"]
            + sorted(
                set("core control_flow routing transformation resilience".split())
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
                            {"type": proc_type, "params": {p: "" for p in params}}
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

related_pages_footer("31_DSL_Визуальный_редактор")
