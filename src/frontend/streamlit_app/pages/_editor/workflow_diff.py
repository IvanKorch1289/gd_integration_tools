"""Workflow diff renderer (S49 W2 TD-009 extraction).

Бывший ``with tab_diff:`` блок из 31_DSL_Visual_Editor.py (Sprint 12 K3 W1).
Side-by-side Graphviz diff двух версий workflow через WorkflowVersionRegistry.
"""

from __future__ import annotations

import streamlit as st


def render_workflow_diff() -> None:
    """Render workflow diff tab: side-by-side Graphviz + step-by-step delta.

    Workflow:
    1. Load WorkflowVersionRegistry singleton.
    2. User picks workflow ID + 2 versions (A=base, B=new).
    3. compute_step_diff → diff_results + 2 color_maps.
    4. Render 2 Graphviz charts side-by-side.
    5. List step-by-step delta (🟢 added, 🔴 removed, 🟠 modified).
    """
    st.subheader("Сравнение workflow — параллельный Graphviz")
    st.caption(
        "Сравните 2 версии workflow по WorkflowVersionRegistry. "
        "Color-coded: зелёный=added, красный=removed, оранжевый=modified."
    )
    try:
        from src.backend.services.dsl_portal import (
            compute_step_diff,
            get_global_registry,
            to_graphviz,
        )

        registry = get_global_registry()
        all_wf_ids = sorted(registry.all_workflow_ids())

        if not all_wf_ids:
            st.info(
                "WorkflowVersionRegistry пуст. Зарегистрируйте workflow "
                "через @workflow_versioned('X.Y.Z')."
            )
        else:
            selected_wf = st.selectbox("ID Workflow", all_wf_ids, key="diff_wf")
            history = registry.history(selected_wf)
            versions = [v.semver for v in history]

            if len(versions) < 2:
                st.warning(f"Нужно ≥2 версии для diff. Текущее: {len(versions)}.")
            else:
                col_a, col_b = st.columns(2)
                with col_a:
                    ver_a = st.selectbox(
                        "Версия A (база)", versions, index=0, key="diff_va"
                    )
                with col_b:
                    ver_b = st.selectbox(
                        "Версия B (новая)", versions, index=1, key="diff_vb"
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
                            st.markdown(f"**Версия A (v{ver_a})**")
                            st.graphviz_chart(
                                to_graphviz(decl_a, color_map=color_map_a)
                            )
                        with col2:
                            st.markdown(f"**Версия B (v{ver_b})**")
                            st.graphviz_chart(
                                to_graphviz(decl_b, color_map=color_map_b)
                            )

                        st.markdown("**Пошаговый diff**")
                        for r in diff_results:
                            icon = {
                                "added": "🟢",
                                "removed": "🔴",
                                "modified": "🟠",
                                "unchanged": "⚪",
                            }.get(r.status, "·")
                            status_ru = {
                                "added": "добавлено",
                                "removed": "удалено",
                                "modified": "изменено",
                                "unchanged": "без изменений",
                            }.get(r.status, r.status)
                            st.write(f"{icon} `{r.identity}` — {status_ru}")
                else:
                    st.info("Выберите две разные версии для сравнения.")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка инициализации diff-view: {exc}")
