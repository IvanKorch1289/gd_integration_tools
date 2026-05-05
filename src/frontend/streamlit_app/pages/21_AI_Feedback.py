"""AI Feedback — страница разметки ответов AI-агентов.

Предоставляет оператору интерфейс для работы с AIFeedbackService:

  * вкладка "На проверку" — список pending ответов с кнопками
    ✅ positive / ❌ negative / ⏭ skip и комментарием;
  * вкладка "Размеченные" — фильтры по метке, агенту, статусу в RAG;
  * кнопка "Перевести в RAG" — ручной запуск FeedbackIndexer;
  * статистика вверху страницы (pending / positive / negative / indexed).

Зависимости: FastAPI-backend должен быть запущен (см. ``manage.py run``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="AI Feedback", page_icon=":brain:", layout="wide")
st.header("AI Feedback Loop")

client = get_api_client()


def _render_stats() -> None:
    """Рисует верхнюю полосу статистики разметки."""
    try:
        stats = client.get_feedback_stats()
    except Exception as exc:
        st.warning(f"Не удалось получить статистику: {exc}")
        return
    cols = st.columns(5)
    cols[0].metric("Pending", stats.get("pending", 0))
    cols[1].metric("Positive", stats.get("positive", 0))
    cols[2].metric("Negative", stats.get("negative", 0))
    cols[3].metric("Skip", stats.get("skip", 0))
    cols[4].metric("Indexed в RAG", stats.get("indexed", 0))


def _render_pending_tab() -> None:
    """Вкладка «На проверку» — список pending-ответов с кнопками разметки."""
    agent_filter = st.text_input(
        "Фильтр по agent_id (опционально)", key="pending_agent"
    )
    try:
        data = client.list_feedback_pending(agent_id=agent_filter or None, limit=50)
    except Exception as exc:
        st.error(f"Ошибка загрузки pending: {exc}")
        return

    items = data.get("items", [])
    st.caption(f"Найдено: {data.get('total', len(items))}")

    for item in items:
        doc_id = item.get("id", "?")
        with st.expander(
            f"[{item.get('agent_id', '—')}] {(item.get('query') or '')[:80]}",
            expanded=False,
        ):
            st.markdown("**Запрос:**")
            st.code(item.get("query", ""))
            st.markdown("**Ответ:**")
            st.code(item.get("response", ""))
            st.caption(
                f"session={item.get('session_id') or '—'} | "
                f"created_at={item.get('created_at')}"
            )

            comment = st.text_input("Комментарий", key=f"cmt-{doc_id}")
            operator = st.text_input("Оператор", key=f"op-{doc_id}")

            b1, b2, b3 = st.columns(3)
            if b1.button("✅ Positive", key=f"pos-{doc_id}"):
                _label(doc_id, "positive", comment, operator)
            if b2.button("❌ Negative", key=f"neg-{doc_id}"):
                _label(doc_id, "negative", comment, operator)
            if b3.button("⏭ Skip", key=f"skp-{doc_id}"):
                _label(doc_id, "skip", comment, operator)


def _label(doc_id: str, label: str, comment: str, operator: str) -> None:
    """Отправляет разметку и перезагружает страницу.

    Args:
        doc_id: Идентификатор документа.
        label: ``positive`` / ``negative`` / ``skip``.
        comment: Комментарий оператора.
        operator: Идентификатор оператора.
    """
    try:
        client.label_feedback(
            doc_id, label=label, comment=comment or None, operator_id=operator or None
        )
        st.success(f"{doc_id}: {label}")
        st.rerun()
    except Exception as exc:
        st.error(f"Не удалось сохранить разметку: {exc}")


def _render_labeled_tab() -> None:
    """Вкладка «Размеченные» — фильтры и таблица."""
    c1, c2, c3 = st.columns(3)
    label = c1.selectbox(
        "Метка", ["", "positive", "negative", "skip"], index=0, key="labeled_label"
    )
    agent_filter = c2.text_input("agent_id", key="labeled_agent")
    rag_filter = c3.selectbox("В RAG", ["—", "да", "нет"], index=0, key="labeled_rag")
    rag_bool = None if rag_filter == "—" else rag_filter == "да"

    try:
        data = client.list_feedback_labeled(
            label=label or None,
            agent_id=agent_filter or None,
            indexed_in_rag=rag_bool,
            limit=200,
        )
    except Exception as exc:
        st.error(f"Ошибка загрузки: {exc}")
        return

    items = data.get("items", [])
    st.caption(f"Найдено: {data.get('total', len(items))}")
    if not items:
        st.info("Нет размеченных ответов по выбранным фильтрам.")
        return
    st.dataframe(
        [
            {
                "id": it.get("id"),
                "agent": it.get("agent_id"),
                "label": it.get("feedback"),
                "в RAG": it.get("indexed_in_rag"),
                "labeled_at": it.get("labeled_at"),
                "query": (it.get("query") or "")[:80],
            }
            for it in items
        ],
        use_container_width=True,
    )


def _render_index_tab() -> None:
    """Вкладка «Индексация» — ручной запуск FeedbackIndexer."""
    st.markdown(
        "Перевод размеченных ответов в RAG-индекс. "
        "`skip`-метки пропускаются; `positive` и `negative` попадают в индекс "
        "с metadata `source=ai_feedback`."
    )
    agent_filter = st.text_input("agent_id (опционально)", key="idx_agent")
    limit = st.number_input("Максимум документов", 1, 1000, 100, key="idx_limit")
    if st.button("Перевести в RAG", type="primary"):
        with st.spinner("Индексирую..."):
            try:
                result = client.index_feedback_to_rag(
                    agent_id=agent_filter or None, limit=int(limit)
                )
                st.success(f"Готово: {result}")
            except Exception as exc:
                st.error(f"Ошибка индексации: {exc}")


_render_stats()
st.divider()

tab1, tab2, tab3 = st.tabs(["На проверку", "Размеченные", "Индексация в RAG"])
with tab1:
    _render_pending_tab()
with tab2:
    _render_labeled_tab()
with tab3:
    _render_index_tab()
