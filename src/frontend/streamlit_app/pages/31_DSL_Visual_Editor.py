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
import yaml as _yaml

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.backend.services.dsl_portal import (  # noqa: E402
    Pipeline,
    load_pipeline_from_yaml,
)
from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="DSL Editor", layout="wide")
st.header("DSL Visual Editor")
st.caption(
    "Round-trip Visual ↔ YAML ↔ Python через RouteBuilder. "
    "Сохранение в YAMLStore через Admin API."
)

# ──────────────────────── Undo/Redo History Stack ───────────────────────────
_MAX_HISTORY = 50


def _push_history():
    """Push current yaml state to history stack."""
    if "yaml_history" not in st.session_state:
        st.session_state.yaml_history = []
    if "yaml_history_index" not in st.session_state:
        st.session_state.yaml_history_index = -1

    # Truncate forward history if we're not at the end
    if st.session_state.yaml_history_index < len(st.session_state.yaml_history) - 1:
        st.session_state.yaml_history = st.session_state.yaml_history[
            : st.session_state.yaml_history_index + 1
        ]

    # Add current state
    st.session_state.yaml_history.append(st.session_state.yaml)
    if len(st.session_state.yaml_history) > _MAX_HISTORY:
        st.session_state.yaml_history.pop(0)
    st.session_state.yaml_history_index = len(st.session_state.yaml_history) - 1


def _can_undo():
    return st.session_state.get("yaml_history_index", -1) > 0


def _can_redo():
    hist = st.session_state.get("yaml_history", [])
    idx = st.session_state.get("yaml_history_index", -1)
    return idx >= 0 and idx < len(hist) - 1


def _undo():
    if _can_undo():
        st.session_state.yaml_history_index -= 1
        st.session_state.yaml = st.session_state.yaml_history[
            st.session_state.yaml_history_index
        ]
        st.rerun()


def _redo():
    if _can_redo():
        st.session_state.yaml_history_index += 1
        st.session_state.yaml = st.session_state.yaml_history[
            st.session_state.yaml_history_index
        ]
        st.rerun()


# Initialize history with current yaml
if "yaml_history" not in st.session_state:
    st.session_state.yaml_history = [st.session_state.yaml]
    st.session_state.yaml_history_index = 0


# ──────────────────────── Processor Step Palette ─────────────────────────────
STEP_PALETTE: dict[str, dict[str, str]] = {
    "log": {
        "title": "Log",
        "desc": "Логирование сообщений на указанном уровне (debug/info/warning/error)",
    },
    "validate": {
        "title": "Validate",
        "desc": "Валидация входных данных по JSON Schema",
    },
    "transform": {
        "title": "Transform",
        "desc": "Трансформация данных через expression (JQ-подобный синтаксис)",
    },
    "dispatch_action": {
        "title": "Dispatch Action",
        "desc": "Диспетчеризация действия по условию",
    },
    "retry": {
        "title": "Retry",
        "desc": "Повтор выполнения при ошибках с max_attempts и delay",
    },
    "redirect": {
        "title": "Redirect",
        "desc": "Редирект запроса на другой URL или endpoint",
    },
    "windowed_dedup": {
        "title": "Windowed Dedup",
        "desc": "Дедупликация по ключу в скользящем окне",
    },
    "windowed_collect": {
        "title": "Windowed Collect",
        "desc": "Сбор событий в окне с опциональной дедупликацией",
    },
    "multicast_routes": {
        "title": "Multicast Routes",
        "desc": "Отправка события в несколько маршрутов параллельно",
    },
    "express_send": {
        "title": "Express Send",
        "desc": "Отправка сообщения в Telegram бот",
    },
    "express_reply": {
        "title": "Express Reply",
        "desc": "Ответ на Telegram сообщение",
    },
    "notify": {
        "title": "Notify",
        "desc": "Уведомление в канал (email/slack/telegram)",
    },
}


def _render_step_palette():
    """Render draggable step palette items using HTML/JS."""
    import json

    palette_json = json.dumps(STEP_PALETTE)

    html = f"""
    <style>
    .step-palette-item {{
        background: #2b3a4a;
        border: 1px solid #4a5a6a;
        border-radius: 6px;
        padding: 8px 12px;
        margin: 4px 0;
        cursor: grab;
        color: #e0e0e0;
        font-size: 13px;
        transition: background 0.2s, transform 0.1s;
        user-select: none;
    }}
    .step-palette-item:hover {{
        background: #3a4a5a;
        transform: translateX(4px);
    }}
    .step-palette-item:active {{
        cursor: grabbing;
    }}
    .step-palette-item .title {{
        font-weight: 600;
        color: #7dd3fc;
    }}
    .step-palette-item .desc {{
        font-size: 11px;
        color: #a0a0a0;
        margin-top: 2px;
    }}
    .palette-header {{
        font-size: 14px;
        font-weight: 600;
        color: #f0f0f0;
        margin-bottom: 8px;
    }}
    </style>
    <div class="palette-header">📦 Step Palette (drag to add)</div>
    <div id="palette-container">
    """
    for key, info in STEP_PALETTE.items():
        html += f"""
        <div class="step-palette-item" draggable="true" data-processor="{key}">
            <div class="title">▶ {info['title']}</div>
            <div class="desc">{info['desc']}</div>
        </div>
        """
    html += """
    </div>
    <script>
    const items = document.querySelectorAll('.step-palette-item');
    let draggedItem = null;

    items.forEach(item => {
        item.addEventListener('dragstart', (e) => {
            draggedItem = item;
            item.style.opacity = '0.5';
            e.dataTransfer.setData('text/plain', item.dataset.processor);
        });
        item.addEventListener('dragend', () => {
            item.style.opacity = '1';
            draggedItem = null;
        });
    });
    </script>
    """

    st.sidebar.markdown("---")
    st.sidebar.subheader("📦 Step Palette")
    st.sidebar.markdown(
        "Drag a processor to the pipeline area below, or click to add:"
    )
    st.components.v1.html(html, height=400, scrolling=True)

    # Show clickable buttons as alternative to drag
    selected_palette_proc = st.sidebar.selectbox(
        "Или выберите процессор:", ["—"] + list(STEP_PALETTE.keys()), key="palette_select"
    )
    if selected_palette_proc != "—":
        st.sidebar.info(f"➡️ Перетащите **{selected_palette_proc}** на панель Pipeline ниже или добавьте через форму слева.")
        # Auto-select in the visual editor form
        st.session_state.vis_proc_type = selected_palette_proc


def _render_drag_drop_pipeline(steps: list[dict], meta: dict) -> list[dict] | None:
    """Render the pipeline with drag-drop reordering using HTML/JS interop.

    Returns the reordered steps list if changed, otherwise None.
    """
    import json

    steps_json = json.dumps(steps)

    html = f"""
    <style>
    .pipeline-container {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .pipeline-item {{
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #0f3460;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 8px 0;
        cursor: grab;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .pipeline-item:hover {{
        background: linear-gradient(135deg, #1f1f3a 0%, #1a2744 100%);
        border-color: #7dd3fc;
        transform: translateX(4px);
    }}
    .pipeline-item.dragging {{
        opacity: 0.5;
        transform: scale(1.02);
    }}
    .pipeline-item .handle {{
        color: #7dd3fc;
        font-size: 18px;
        cursor: grab;
    }}
    .pipeline-item .step-num {{
        background: #7dd3fc;
        color: #1a1a2e;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 12px;
        flex-shrink: 0;
    }}
    .pipeline-item .step-content {{
        flex: 1;
    }}
    .pipeline-item .step-type {{
        font-weight: 600;
        color: #7dd3fc;
        font-size: 14px;
    }}
    .pipeline-item .step-params {{
        font-size: 11px;
        color: #a0a0a0;
        margin-top: 2px;
    }}
    .pipeline-empty {{
        text-align: center;
        padding: 40px;
        color: #6b7280;
        border: 2px dashed #374151;
        border-radius: 8px;
        margin: 16px 0;
    }}
    .drop-zone {{
        min-height: 60px;
        border: 2px dashed #374151;
        border-radius: 8px;
        padding: 8px;
        transition: border-color 0.2s, background 0.2s;
    }}
    .drop-zone.drag-over {{
        border-color: #7dd3fc;
        background: rgba(125, 211, 252, 0.1);
    }}
    </style>

    <div class="pipeline-container">
        <div id="drop-zone" class="drop-zone">
            <div id="pipeline-list">
            </div>
        </div>
        <div id="empty-msg" class="pipeline-empty" style="display: none;">
            �_empty_placeholder😐 Перетащите процессор из палитры или добавьте через форму слева
        </div>
    </div>

    <script>
    const stepsData = {steps_json};

    function renderSteps(steps) {{
        const list = document.getElementById('pipeline-list');
        const emptyMsg = document.getElementById('empty-msg');
        const dropZone = document.getElementById('drop-zone');

        if (!steps || steps.length === 0) {{
            list.innerHTML = '';
            emptyMsg.style.display = 'block';
            dropZone.style.display = 'block';
            return;
        }}

        emptyMsg.style.display = 'none';
        list.innerHTML = steps.map((step, i) => `
            <div class="pipeline-item" draggable="true" data-index="${{i}}">
                <span class="handle">☰</span>
                <span class="step-num">${{i + 1}}</span>
                <div class="step-content">
                    <div class="step-type">▶ ${{step.type}}</div>
                    <div class="step-params">${{Object.keys(step.params || {{}}).length > 0
                        ? Object.entries(step.params || {{}}).map(([k,v]) => `${{k}}=${{v}}`).join(', ')
                        : 'без параметров'}}</div>
                </div>
            </div>
        `).join('');

        // Attach drag events
        const items = list.querySelectorAll('.pipeline-item');
        items.forEach(item => {{
            item.addEventListener('dragstart', handleDragStart);
            item.addEventListener('dragend', handleDragEnd);
        }});

        dropZone.style.display = 'block';
    }}

    let draggedIndex = null;

    function handleDragStart(e) {{
        draggedIndex = parseInt(e.target.dataset.index);
        e.target.classList.add('dragging');
        e.dataTransfer.setData('text/plain', e.target.dataset.index);
        e.dataTransfer.effectAllowed = 'move';
    }}

    function handleDragEnd(e) {{
        e.target.classList.remove('dragging');
        draggedIndex = null;
        // Remove drag-over from all zones
        document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    }}

    // Drop zone events
    const dropZone = document.getElementById('drop-zone');
    dropZone.addEventListener('dragover', (e) => {{
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        dropZone.classList.add('drag-over');
    }});
    dropZone.addEventListener('dragleave', () => {{
        dropZone.classList.remove('drag-over');
    }});
    dropZone.addEventListener('drop', (e) => {{
        e.preventDefault();
        dropZone.classList.remove('drag-over');

        const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
        const toIndex = draggedIndex;

        if (!isNaN(fromIndex) && fromIndex !== toIndex) {{
            // Reorder steps
            const newSteps = [...stepsData];
            const [moved] = newSteps.splice(fromIndex, 1);
            newSteps.splice(toIndex, 0, moved);

            // Dispatch custom event for Streamlit
            const event = new CustomEvent('reorder-steps', {{
                detail: {{ steps: newSteps }},
                bubbles: true
            }});
            window.parent.document.dispatchEvent(event);
        }}
    }});

    // Handle reordering within the list
    function handleDragOver(e) {{
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
    }}

    renderSteps(stepsData);
    </script>
    """

    st.components.v1.html(html, height=max(200, len(steps) * 70 + 80), scrolling=False)

    # Handle reorder events via JavaScript interop using a hidden element
    # We use query_params to communicate the new order
    st.markdown("""
    <script>
    window.addEventListener('message', function(e) {
        if (e.data && e.data.type === 'reorder-steps') {
            const params = new URLSearchParams();
            params.set('reorder', JSON.stringify(e.data.steps));
            window.parent.location.search = params.toString();
        }
    });
    </script>
    """, unsafe_allow_html=True)

    return None


def _default_yaml() -> str:
    """YAML-шаблон по умолчанию для нового маршрута."""
    return (
        "route_id: my.route\n"
        "source: internal:my\n"
        "description: Новый маршрут\n"
        "processors:\n"
        "  - log:\n"
        "      level: info\n"
    )


if "yaml" not in st.session_state:
    st.session_state.yaml = _default_yaml()

if "last_load_route" not in st.session_state:
    st.session_state.last_load_route = None


def _try_load(yaml_str: str) -> tuple[Pipeline | None, str | None]:
    """Локально парсит YAML в Pipeline.

    Returns:
        Pipeline или None и текст ошибки.
    """
    try:
        return load_pipeline_from_yaml(yaml_str), None
    except Exception as exc:  # noqa: BLE001 — UI должен показать любую ошибку.
        return None, str(exc)


def _yaml_to_steps(yaml_str: str) -> tuple[dict, list[dict]]:
    """Извлекает meta (route_id/source/description) и список шагов из YAML."""
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


def _build_yaml_from_steps(meta: dict, steps: list[dict]) -> str:
    """Собирает YAML из meta и шагов (формат, понятный yaml_loader)."""
    out: dict = {"route_id": meta.get("route_id") or "my.route"}
    if meta.get("source"):
        out["source"] = meta["source"]
    if meta.get("description"):
        out["description"] = meta["description"]
    if steps:
        out["processors"] = [{s["type"]: s.get("params") or {}} for s in steps]
    return _yaml.dump(out, allow_unicode=True, sort_keys=False)


client = get_api_client()


# ──────────────────────── Render Step Palette in Sidebar ─────────────────────
_render_step_palette()


with st.sidebar:
    # Undo/Redo controls
    st.subheader("↩️ История изменений")
    hist_cols = st.columns([1, 1])
    hist_cols[0].button(
        "↩️ Undo",
        use_container_width=True,
        disabled=not _can_undo(),
        on_click=_undo,
    )
    hist_cols[1].button(
        "↪️ Redo",
        use_container_width=True,
        disabled=not _can_redo(),
        on_click=_redo,
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
        st.session_state.yaml = _default_yaml()
        st.session_state.last_load_route = None
        st.rerun()

    st.divider()

    st.subheader("Сохранение")
    pipeline_check, err_check = _try_load(st.session_state.yaml)
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
                st.session_state.yaml = _default_yaml()
                st.session_state.last_load_route = None
                st.rerun()
            else:
                st.error("Ошибка удаления")


tab_visual, tab_yaml, tab_python, tab_diff = st.tabs(
    ["Visual", "YAML", "Python", "Workflow Diff"]
)


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

with tab_visual:
    # Handle reorder from drag-drop via query params
    import json as _json

    query_params = st.query_params
    if "reorder" in query_params:
        try:
            reordered_steps = _json.loads(query_params["reorder"])
            if isinstance(reordered_steps, list):
                meta, current_steps = _yaml_to_steps(st.session_state.yaml)
                if len(reordered_steps) == len(current_steps):
                    st.session_state.yaml = _build_yaml_from_steps(meta, reordered_steps)
                    _push_history()
        except Exception:  # noqa: BLE001
            pass
        # Clear the query param
        query_params.clear()
        st.rerun()

    meta, steps = _yaml_to_steps(st.session_state.yaml)

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
            st.session_state.yaml = _build_yaml_from_steps(
                {
                    "route_id": new_route_id,
                    "source": new_source,
                    "description": new_desc,
                },
                steps,
            )
            _push_history()
            st.rerun()

    with col_right:
        st.subheader("🔗 Pipeline (drag to reorder)")
        st.caption("Перетащите процессоры для изменения порядка")

        # Render drag-drop pipeline
        _render_drag_drop_pipeline(steps, meta)

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
                st.session_state.yaml = _build_yaml_from_steps(
                    {
                        "route_id": new_route_id,
                        "source": new_source,
                        "description": new_desc,
                    },
                    steps,
                )
                _push_history()
                st.rerun()
            if c3.button("↓", key=f"down_{i}", disabled=i == len(steps) - 1):
                steps[i], steps[i + 1] = steps[i + 1], steps[i]
                st.session_state.yaml = _build_yaml_from_steps(
                    {
                        "route_id": new_route_id,
                        "source": new_source,
                        "description": new_desc,
                    },
                    steps,
                )
                _push_history()
                st.rerun()
            if c4.button("✕", key=f"del_{i}"):
                steps.pop(i)
                st.session_state.yaml = _build_yaml_from_steps(
                    {
                        "route_id": new_route_id,
                        "source": new_source,
                        "description": new_desc,
                    },
                    steps,
                )
                _push_history()
                st.rerun()

        rebuilt = _build_yaml_from_steps(
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
        _push_history()

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

    pipeline, err = _try_load(st.session_state.yaml)
    if err:
        st.error(f"Локальная валидация: {err}")
    else:
        with st.expander("JSON spec"):
            st.json(pipeline.to_dict())


with tab_python:
    pipeline, err = _try_load(st.session_state.yaml)
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
