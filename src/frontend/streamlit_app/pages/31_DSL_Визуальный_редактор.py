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
    from src.frontend.streamlit_app.pages._editor.visual.tab_visual import (
        render_visual_tab,
    )
    render_visual_tab()

with tab_yaml:
    from src.frontend.streamlit_app.pages._editor.visual.tab_yaml import (
        render_yaml_tab,
    )
    render_yaml_tab(client)

with tab_python:
    from src.frontend.streamlit_app.pages._editor.visual.tab_python import (
        render_python_tab,
    )
    render_python_tab()

# ── Sprint 12 K3 W1: Workflow Diff ──
with tab_diff:
    render_workflow_diff()

with tab_canvas:
    from src.frontend.streamlit_app.pages._editor.visual.tab_canvas import (
        render_canvas_tab,
    )
    render_canvas_tab(client)

related_pages_footer("31_DSL_Визуальный_редактор")
