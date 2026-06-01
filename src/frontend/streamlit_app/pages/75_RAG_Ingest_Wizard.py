"""Streamlit-страница 75 — RAG Ingest Wizard (К4 MVP, Шаг 8).

5 шагов: upload → split (preview) → embed (выбор провайдера) → upsert (start) → verify.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_client_k4 import K4APIClient

st.set_page_config(page_title="RAG Ingest Wizard", page_icon="📥", layout="wide")
st.title("📥 RAG Ingest Wizard")

if "ingest_step" not in st.session_state:
    st.session_state["ingest_step"] = 1

client = K4APIClient()
step = int(st.session_state["ingest_step"])
st.progress(step / 5)
st.caption(f"Шаг {step} / 5")


if step == 1:
    st.subheader("1. Загрузка файлов")
    uploaded = st.file_uploader(
        "Документы (txt / md / pdf)", accept_multiple_files=True, type=None
    )
    if uploaded:
        st.session_state["ingest_files"] = uploaded
        if st.button("Далее →"):
            st.session_state["ingest_step"] = 2
            st.rerun()

elif step == 2:
    st.subheader("2. Предпросмотр chunking (informational)")
    files = st.session_state.get("ingest_files", [])
    st.write(f"Файлов к загрузке: **{len(files)}**")
    for f in files:
        st.write(
            f"• `{getattr(f, 'name', 'unnamed')}` ({getattr(f, 'size', '?')} bytes)"
        )
    if st.button("Далее →"):
        st.session_state["ingest_step"] = 3
        st.rerun()

elif step == 3:
    st.subheader("3. Выбор embedding-провайдера")
    providers = client.list_embedding_providers() or [
        "sentence-transformers",
        "bge-m3",
        "openai",
    ]
    st.session_state["ingest_provider"] = st.selectbox("Provider", providers)
    st.session_state["ingest_collection"] = st.text_input("Collection", value="default")
    if st.button("Далее →"):
        st.session_state["ingest_step"] = 4
        st.rerun()

elif step == 4:
    st.subheader("4. Запуск ingest")
    files = st.session_state.get("ingest_files", [])
    collection = st.session_state.get("ingest_collection", "default")
    if st.button("Старт", type="primary"):
        result = client.rag_ingest_start(files=files, collection=collection)
        st.session_state["ingest_task_id"] = result.get("task_id")
        st.session_state["ingest_result"] = result
        if result.get("task_id"):
            st.session_state["ingest_step"] = 5
            st.rerun()
        else:
            st.error(f"Не удалось запустить ingest: {result}")

elif step == 5:
    st.subheader("5. Verification")
    task_id = st.session_state.get("ingest_task_id")
    if task_id:
        status = client.rag_ingest_status(task_id) or st.session_state.get(
            "ingest_result", {}
        )
        st.json(status)
    else:
        st.warning("task_id отсутствует.")
    if st.button("Начать заново"):
        for key in (
            "ingest_step",
            "ingest_files",
            "ingest_provider",
            "ingest_collection",
            "ingest_task_id",
            "ingest_result",
        ):
            st.session_state.pop(key, None)
        st.rerun()
