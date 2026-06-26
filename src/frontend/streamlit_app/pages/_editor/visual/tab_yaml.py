"""YAML tab — extracted from pages/31_DSL_Визуальный_редактор (S173).

YAML text_area editor + Validate/Diff buttons + JSON spec expander.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.pages._editor.yaml_sync import (
    push_history,
    try_load,
)


def render_yaml_tab(client) -> None:
    """Render YAML tab: raw editor + server validate/diff + JSON spec."""
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