"""AI Feedback — страница разметки ответов AI-агентов + DSPy training.

Вкладки:
* На проверку
* Размеченные
* Индексация в RAG
* DSPy Training
* Labeled Counts
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page, related_pages_footer

setup_page()
st.header("Цикл разметки AI")

client = get_api_client()


def _render_stats() -> None:
    try:
        stats = client.get_feedback_stats()
    except Exception as exc:
        st.warning(f"Не удалось получить статистику: {exc}")
        return
    cols = st.columns(5)
    cols[0].metric("На проверку", stats.get("pending", 0))
    cols[1].metric("Положительные", stats.get("positive", 0))
    cols[2].metric("Отрицательные", stats.get("negative", 0))
    cols[3].metric("Пропущено", stats.get("skip", 0))
    cols[4].metric("Indexed в RAG", stats.get("indexed", 0))


def _render_pending_tab() -> None:
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
    try:
        client.label_feedback(
            doc_id, label=label, comment=comment or None, operator_id=operator or None
        )
        st.success(f"{doc_id}: {label}")
        st.rerun()
    except Exception as exc:
        st.error(f"Не удалось сохранить разметку: {exc}")


def _render_labeled_tab() -> None:
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
        width='stretch',
    )


def _render_index_tab() -> None:
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


def _render_dspy_tab() -> None:
    st.markdown(
        "Просмотр labeled feedback и DSPy training runs. "
        "Активируется feature-flag `dspy_feedback_loop`."
    )
    try:
        data = client.get("/admin/feedback/training-runs?limit=10")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка: {exc}")
        data = {"runs": [], "count": 0}
    runs = data.get("runs", []) if isinstance(data, dict) else []
    if not runs:
        st.info(
            "Нет завершённых runs. Cron `ai_feedback_dspy_nightly` запускается в 03:00 при включённом feature-flag."
        )
    else:
        for r in runs:
            with st.expander(f"Run {r.get('id')} — {r.get('completed_at')}"):
                st.json(r)


def _render_counts_tab() -> None:
    tenant = st.text_input("Tenant ID (опционально)", key="counts_tenant")
    try:
        data = client.get(
            f"/admin/feedback/labeled-count{('?tenant_id=' + tenant) if tenant else ''}"
        )
        count = data.get("count", 0) if isinstance(data, dict) else 0
        st.metric("Размеченные ответы", count)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка: {exc}")


_render_stats()
st.divider()

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "На проверку",
        "Размеченные",
        "Индексация в RAG",
        "DSPy Training",
        "Счётчики разметки",
    ]
)
with tab1:
    _render_pending_tab()
with tab2:
    _render_labeled_tab()
with tab3:
    _render_index_tab()
with tab4:
    _render_dspy_tab()
with tab5:
    _render_counts_tab()

related_pages_footer("21_AI_Обратная_связь")
