"""DSL Visual Editor sidebar — extracted from pages/31_DSL_Визуальный_редактор (S173).

Sidebar panel: Undo/Redo + Routes storage + Save/Create/Update/Delete buttons.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.pages._editor.history import (
    can_redo,
    can_undo,
    redo,
    undo,
)
from src.frontend.streamlit_app.pages._editor.yaml_sync import try_load


def render_editor_sidebar(client) -> None:
    """Render full sidebar panel (history + routes + save)."""
    # Undo/Redo controls
    st.subheader("↩️ История изменений")
    hist_cols = st.columns([1, 1])
    hist_cols[0].button(
        "↩️ Undo", width='stretch', disabled=not can_undo(), on_click=undo
    )
    hist_cols[1].button(
        "↪️ Redo", width='stretch', disabled=not can_redo(), on_click=redo
    )
    if st.session_state.get("yaml_history"):
        idx = st.session_state.get("yaml_history_index", 0)
        total = len(st.session_state.yaml_history)
        st.caption(f"Шаг {idx + 1} из {total}")

    st.divider()

    # Routes storage
    st.subheader("Хранилище маршрутов")
    routes = client.list_dsl_routes()
    selected = st.selectbox("Открыть существующий", ["—"] + routes, key="route_select")
    cols = st.columns(2)
    if cols[0].button("Загрузить", width='stretch', disabled=selected == "—"):
        detail = client.get_dsl_route(selected)
        if detail and "yaml" in detail:
            st.session_state.yaml = detail["yaml"]
            st.session_state.last_load_route = selected
            st.success(f"Загружен маршрут {selected!r}")
            st.rerun()
        else:
            st.error("Не удалось загрузить маршрут")
    if cols[1].button("Новый", width='stretch'):
        from src.frontend.streamlit_app.pages._editor.yaml_sync import default_yaml
        st.session_state.yaml = default_yaml()
        st.session_state.last_load_route = None
        st.rerun()

    st.divider()

    # Save buttons
    st.subheader("Сохранение")
    pipeline_check, err_check = try_load(st.session_state.yaml)
    if err_check:
        st.error(f"YAML невалиден: {err_check}")
    else:
        st.caption(f"route_id: `{pipeline_check.route_id}`")
        if st.button("Сохранить (создать)", width='stretch'):
            try:
                client.create_dsl_route(st.session_state.yaml)
                st.success(f"Создан {pipeline_check.route_id!r}")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ошибка создания: {exc}")
        if st.button("Обновить (PUT)", width='stretch'):
            try:
                client.update_dsl_route(pipeline_check.route_id, st.session_state.yaml)
                st.success(f"Обновлён {pipeline_check.route_id!r}")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ошибка обновления: {exc}")
        if st.session_state.last_load_route and st.button(
            "Удалить", width='stretch'
        ):
            if client.delete_dsl_route(st.session_state.last_load_route):
                st.success(f"Удалён {st.session_state.last_load_route!r}")
                from src.frontend.streamlit_app.pages._editor.yaml_sync import (
                    default_yaml,
                )
                st.session_state.yaml = default_yaml()
                st.session_state.last_load_route = None
                st.rerun()
            else:
                st.error("Ошибка удаления")
