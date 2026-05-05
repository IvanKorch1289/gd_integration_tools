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

from src.backend.dsl.engine.pipeline import Pipeline  # noqa: E402
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml  # noqa: E402
from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="DSL Editor", layout="wide")
st.header("DSL Visual Editor")
st.caption(
    "Round-trip Visual ↔ YAML ↔ Python через RouteBuilder. "
    "Сохранение в YAMLStore через Admin API."
)


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


with st.sidebar:
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


tab_visual, tab_yaml, tab_python = st.tabs(["Visual", "YAML", "Python"])


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
            st.rerun()

    with col_right:
        st.subheader("Pipeline")
        if not steps:
            st.info("Пусто. Добавьте процессор слева.")
        for i, step in enumerate(steps):
            c1, c2, c3 = st.columns([5, 1, 1])
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
                st.rerun()
            if c3.button("✕", key=f"del_{i}"):
                steps.pop(i)
                st.session_state.yaml = _build_yaml_from_steps(
                    {
                        "route_id": new_route_id,
                        "source": new_source,
                        "description": new_desc,
                    },
                    steps,
                )
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
