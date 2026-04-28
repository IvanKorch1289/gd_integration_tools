"""Streamlit-страница для notebooks (Wave 9.1).

Позволяет: создать notebook, редактировать markdown, посмотреть
историю версий, восстановить старую, soft-delete.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import streamlit as st

from src.services.notebooks import get_notebook_service


def _run(coro: Any) -> Any:
    """Синхронная обёртка для async-вызовов в Streamlit."""
    return asyncio.run(coro)


def _format_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


st.set_page_config(page_title="Notebooks", page_icon="📒", layout="wide")
st.title("📒 Notebooks")
st.caption("Версионируемые заметки (Wave 9.1, MongoDB append-only).")

service = get_notebook_service()

with st.sidebar:
    st.subheader("Создать notebook")
    with st.form("create_form"):
        new_title = st.text_input("Заголовок")
        new_tags = st.text_input("Теги (через запятую)")
        new_author = st.text_input("Автор", value=st.session_state.get("user", "anon"))
        new_content = st.text_area("Markdown-контент", height=200)
        submitted = st.form_submit_button("Создать")
        if submitted and new_title:
            tags = [t.strip() for t in new_tags.split(",") if t.strip()]
            notebook = _run(
                service.create(
                    title=new_title,
                    content=new_content,
                    created_by=new_author or "anon",
                    tags=tags,
                )
            )
            st.success(f"Создан notebook {notebook.id[:8]}…")
            st.session_state["selected_notebook"] = notebook.id
            st.rerun()

    st.divider()
    filter_tag = st.text_input("Фильтр по тегу", value="")
    show_deleted = st.checkbox("Показывать удалённые", value=False)

notebooks = _run(
    service.list_all(tag=filter_tag or None, include_deleted=show_deleted, limit=200)
)

col_list, col_detail = st.columns([1, 2])

with col_list:
    st.subheader(f"Notebooks ({len(notebooks)})")
    for nb in notebooks:
        label = f"{'🗑 ' if nb.is_deleted else ''}{nb.title} (v{nb.latest_version})"
        if st.button(label, key=f"select_{nb.id}", use_container_width=True):
            st.session_state["selected_notebook"] = nb.id
            st.rerun()
        st.caption(f"{_format_dt(nb.updated_at)} · {', '.join(nb.tags) or '—'}")

selected_id = st.session_state.get("selected_notebook")

with col_detail:
    if not selected_id:
        st.info("Выберите notebook слева или создайте новый.")
    else:
        notebook = _run(service.get(selected_id))
        if notebook is None:
            st.error("Notebook не найден.")
        else:
            st.subheader(notebook.title)
            st.caption(
                f"id={notebook.id} · v{notebook.latest_version} · "
                f"автор={notebook.created_by} · теги={', '.join(notebook.tags) or '—'}"
            )

            tab_edit, tab_preview, tab_history = st.tabs(
                ["Редактировать", "Preview", "История версий"]
            )

            with tab_edit:
                with st.form("edit_form"):
                    user = st.text_input(
                        "Пользователь", value=st.session_state.get("user", "anon")
                    )
                    summary = st.text_input("Комментарий к версии")
                    new_content = st.text_area(
                        "Markdown-контент", value=notebook.current_content, height=400
                    )
                    save = st.form_submit_button("Сохранить новую версию")
                    if save:
                        updated = _run(
                            service.update_content(
                                notebook_id=notebook.id,
                                content=new_content,
                                user=user or "anon",
                                summary=summary or None,
                            )
                        )
                        if updated:
                            st.success(f"Сохранена версия {updated.latest_version}")
                            st.rerun()
                        else:
                            st.error("Не удалось сохранить версию.")

                if st.button("🗑 Удалить (soft)", key="delete"):
                    _run(service.delete(notebook.id))
                    st.session_state.pop("selected_notebook", None)
                    st.rerun()

            with tab_preview:
                st.markdown(notebook.current_content or "_(пусто)_")

            with tab_history:
                for v in reversed(notebook.versions):
                    with st.expander(
                        f"v{v.version} · {_format_dt(v.changed_at)} · {v.changed_by}"
                    ):
                        st.code(v.content, language="markdown")
                        if v.summary:
                            st.caption(f"Комментарий: {v.summary}")
                        if v.version != notebook.latest_version and st.button(
                            f"Восстановить v{v.version}", key=f"restore_{v.version}"
                        ):
                            _run(
                                service.restore_version(
                                    notebook_id=notebook.id,
                                    version=v.version,
                                    user=st.session_state.get("user", "anon"),
                                )
                            )
                            st.rerun()
