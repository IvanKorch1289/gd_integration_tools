"""W25.2 — DSL Builder: просмотр и сохранение runtime-Pipeline в YAML.

Минималистичная страница: селектор route_id → preview YAML → diff с
текущим файлом → кнопка Save (видна только в development).

Layer policy: страница импортирует только ``services/dsl/builder_service``
и stdlib/streamlit. Прямые impl-импорты запрещены (см. CLAUDE.md).

Для редактирования процессоров используется существующая страница
``9_DSL_Visual_Editor`` (Visual ↔ YAML ↔ Python через REST API).
Эта же — write-back из runtime'а.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.services.dsl.builder_service import (  # noqa: E402
    DSLBuilderService,
    get_dsl_builder_service,
)

st.set_page_config(page_title="DSL Builder (write-back)", layout="wide")
st.header("DSL Builder — write-back YAML")
st.caption(
    "Сохраняет runtime-Pipeline (RouteRegistry) в YAMLStore. "
    "Доступно только в development (env-guard). Для редактирования — стр. 9."
)


def _service() -> DSLBuilderService:
    return get_dsl_builder_service()


def _render() -> None:
    svc = _service()
    routes = svc.list_routes()
    if not routes:
        st.warning("В RouteRegistry нет зарегистрированных маршрутов.")
        return

    cols = st.columns([2, 1])
    with cols[0]:
        route_id = st.selectbox("Route", options=routes, key="dsl_builder_route_id")
    with cols[1]:
        st.metric("Всего routes", len(routes))

    pipeline = svc.get_pipeline(route_id) if route_id else None
    if pipeline is None:
        st.info("Выбери route в селекторе.")
        return

    yaml_text = svc.render_yaml(route_id)
    diff_text = svc.preview_diff(route_id)

    tabs = st.tabs(["YAML preview", "Diff vs YAMLStore"])
    with tabs[0]:
        if yaml_text:
            st.code(yaml_text, language="yaml")
        else:
            st.warning(
                "to_yaml() вернул пустое представление — у Pipeline нет "
                "процессоров с реализованным to_spec(). См. write_back.md."
            )
    with tabs[1]:
        if diff_text:
            st.code(diff_text, language="diff")
        else:
            st.success("Изменений относительно YAMLStore нет.")

    st.divider()
    st.subheader("Write-back")
    write_enabled = svc.is_write_enabled()
    if not write_enabled:
        st.warning(
            "Кнопка Save отключена: environment != development. "
            "Используй CLI `manage.py dsl write-yaml` локально."
        )

    cols = st.columns(2)
    with cols[0]:
        dry_clicked = st.button("Preview Save (dry-run)", use_container_width=True)
    with cols[1]:
        save_clicked = st.button(
            "Save to YAML",
            type="primary",
            disabled=not write_enabled,
            use_container_width=True,
        )

    if dry_clicked:
        result = svc.save_route(route_id, dry_run=True)
        st.info(f"Path: `{result.path}` (would write={result.written})")
        if result.diff:
            st.code(result.diff, language="diff")
        else:
            st.success("Diff пуст — файл совпадает с runtime.")
    if save_clicked and write_enabled:
        try:
            result = svc.save_route(route_id)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed: {exc}")
            return
        if result.written:
            st.success(f"Saved → {result.path}")
        else:
            st.warning(f"Skipped: {result.reason}")


_render()
