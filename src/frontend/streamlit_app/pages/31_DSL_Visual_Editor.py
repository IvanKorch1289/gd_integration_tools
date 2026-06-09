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

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.backend.services.dsl_portal import load_pipeline_from_yaml  # noqa: E402
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

setup_page("DSL Editor", "")
st.header("DSL Visual Editor")
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
        "description": "New route",
    }


client = get_api_client()


# ──────────────────────── Render Step Palette in Sidebar ─────────────────────
render_step_palette()


with st.sidebar:
    # Undo/Redo controls
    st.subheader("↩️ История изменений")
    hist_cols = st.columns([1, 1])
    hist_cols[0].button(
        "↩️ Undo", use_container_width=True, disabled=not can_undo(), on_click=undo
    )
    hist_cols[1].button(
        "↪️ Redo", use_container_width=True, disabled=not can_redo(), on_click=redo
    )
    if st.session_state.get("yaml_history"):
        idx = st.session_state.get("yaml_history_index", 0)
        total = len(st.session_state.yaml_history)
        st.caption(f"Шаг {idx + 1} из {total}")

    st.divider()

    st.subheader("Хранилище маршрутов")
    routes = client.list_dsl_routes()
    selected = st.selectbox("Открыть существующий", ["—"] + routes, key="route_select")
    cols = st.columns(2)
    if cols[0].button("Загрузить", use_container_width=True, disabled=selected == "—"):
        detail = client.get_dsl_route(selected)
        if detail and "yaml" in detail:
            st.session_state.yaml = detail["yaml"]
            st.session_state.last_load_route = selected
            st.success(f"Загружен маршрут {selected!r}")
            st.rerun()
        else:
            st.error("Не удалось загрузить маршрут")
    if cols[1].button("Новый", use_container_width=True):
        st.session_state.yaml = default_yaml()
        st.session_state.last_load_route = None
        st.rerun()

    st.divider()

    st.subheader("Сохранение")
    pipeline_check, err_check = try_load(st.session_state.yaml)
    if err_check:
        st.error(f"YAML невалиден: {err_check}")
    else:
        st.caption(f"route_id: `{pipeline_check.route_id}`")
        if st.button("Сохранить (создать)", use_container_width=True):
            try:
                client.create_dsl_route(st.session_state.yaml)
                st.success(f"Создан {pipeline_check.route_id!r}")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ошибка создания: {exc}")
        if st.button("Обновить (PUT)", use_container_width=True):
            try:
                client.update_dsl_route(pipeline_check.route_id, st.session_state.yaml)
                st.success(f"Обновлён {pipeline_check.route_id!r}")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ошибка обновления: {exc}")
        if st.session_state.last_load_route and st.button(
            "Удалить", use_container_width=True
        ):
            if client.delete_dsl_route(st.session_state.last_load_route):
                st.success(f"Удалён {st.session_state.last_load_route!r}")
                st.session_state.yaml = default_yaml()
                st.session_state.last_load_route = None
                st.rerun()
            else:
                st.error("Ошибка удаления")


tab_visual, tab_yaml, tab_python, tab_diff, tab_canvas = st.tabs(
    ["Visual", "YAML", "Python", "Workflow Diff", "Canvas (Drag-Drop)"]
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

        if st.button("+ Добавить процессор", use_container_width=True):
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
        st.subheader("🔗 Pipeline (drag to reorder)")
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
    if cols[0].button("Validate (server)", use_container_width=True):
        result = client.validate_dsl_route(st.session_state.yaml)
        if result.get("valid"):
            st.success(
                f"OK · route_id={result.get('route_id')} · "
                f"процессоров: {result.get('processors_count', 0)}"
            )
        else:
            st.error(f"Ошибка: {result.get('error')}")

    if (
        cols[1].button("Diff vs saved", use_container_width=True)
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
        with st.expander("JSON spec"):
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
    st.subheader("Workflow Diff — side-by-side Graphviz")
    st.caption(
        "Сравните 2 версии workflow по WorkflowVersionRegistry. "
        "Color-coded: зелёный=added, красный=removed, оранжевый=modified."
    )
    try:
        from src.backend.dsl.workflow.versioning import get_global_registry
        from src.backend.dsl.workflow.visualize import compute_step_diff, to_graphviz

        registry = get_global_registry()
        all_wf_ids = sorted(registry.all_workflow_ids())

        if not all_wf_ids:
            st.info(
                "WorkflowVersionRegistry пуст. Зарегистрируйте workflow "
                "через @workflow_versioned('X.Y.Z')."
            )
        else:
            selected_wf = st.selectbox("Workflow ID", all_wf_ids, key="diff_wf")
            history = registry.history(selected_wf)
            versions = [v.semver for v in history]

            if len(versions) < 2:
                st.warning(f"Нужно ≥2 версии для diff. Текущее: {len(versions)}.")
            else:
                col_a, col_b = st.columns(2)
                with col_a:
                    ver_a = st.selectbox(
                        "Version A (база)", versions, index=0, key="diff_va"
                    )
                with col_b:
                    ver_b = st.selectbox(
                        "Version B (новая)", versions, index=1, key="diff_vb"
                    )

                if ver_a and ver_b and ver_a != ver_b:
                    rec_a = next((v for v in history if v.semver == ver_a), None)
                    rec_b = next((v for v in history if v.semver == ver_b), None)

                    decl_a = getattr(rec_a, "declaration", None)
                    decl_b = getattr(rec_b, "declaration", None)

                    if decl_a is None or decl_b is None:
                        st.error(
                            "Версия не содержит declaration. Расширьте "
                            "WorkflowVersion для хранения WorkflowDeclaration."
                        )
                    else:
                        diff_results, color_map_a, color_map_b = compute_step_diff(
                            decl_a, decl_b
                        )
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Version A (v{ver_a})**")
                            st.graphviz_chart(
                                to_graphviz(decl_a, color_map=color_map_a)
                            )
                        with col2:
                            st.markdown(f"**Version B (v{ver_b})**")
                            st.graphviz_chart(
                                to_graphviz(decl_b, color_map=color_map_b)
                            )

                        st.markdown("**Step-by-step diff**")
                        for r in diff_results:
                            icon = {
                                "added": "🟢",
                                "removed": "🔴",
                                "modified": "🟠",
                                "unchanged": "⚪",
                            }.get(r.status, "·")
                            st.write(f"{icon} `{r.identity}` — {r.status}")
                else:
                    st.info("Выберите две разные версии для сравнения.")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка инициализации diff-view: {exc}")

# ═══════════════════════════════════════════════════════════════════════════════
# Canvas (Drag-Drop) tab — adapted from 40_dsl_visual_editor.py
# ═══════════════════════════════════════════════════════════════════════════════

with tab_canvas:
    col_palette, col_canvas, col_props = st.columns([1, 2, 1])

    with col_palette:
        st.subheader("📦 Step Palette")

        palette_category = st.selectbox(
            "Category",
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
                        sync_yaml()
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
                    meta, steps = yaml_to_steps(detail["yaml"])
                    st.session_state.meta_route = meta
                    st.session_state.canvas_steps = steps
                    st.session_state.selected_step_index = None
                    sync_yaml()
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
            sync_yaml()
            st.rerun()

    with col_canvas:
        st.subheader("🎨 Canvas — Pipeline Steps")

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
            st.info("🖱️ Drag steps from palette or click ➕ to add. Configure on right.")
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
                            if c1.button(f"#{i + 1}", key=f"sel_{i}", help="Select"):
                                st.session_state.selected_step_index = i
                                st.rerun()

                        with c2:
                            st.markdown(f"**{icon} {step['type']}**")
                            if params_str:
                                st.caption(f"_{params_str}_")

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
                            sync_yaml()
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
                            sync_yaml()
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
                            sync_yaml()
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
            pipeline = load_pipeline_from_yaml(st.session_state.yaml_output)
            with st.expander("JSON spec"):
                st.json(pipeline.to_dict())
            with st.expander("Python code"):
                st.code(pipeline.to_python(), language="python")
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Spec unavailable: {exc}")
