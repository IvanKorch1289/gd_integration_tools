"""RAG Console — UI для управления RAG (Wave 10.1).

Позволяет:
* посмотреть `/api/v1/rag/stats` (опционально по namespace);
* выполнить семантический поиск ``/api/v1/rag/search``;
* загрузить документ через multipart ``/api/v1/rag/upload``.
"""

from __future__ import annotations

import json

import streamlit as st

from src.frontend.streamlit_app.api_clients.rag import RAGClient
from src.frontend.streamlit_app.shared.components import setup_page, related_pages_footer

setup_page(layout="wide", initial_sidebar_state="expanded")

st.title("Консоль RAG")

client = RAGClient()

with st.expander("Статус RAG"):
    namespace = st.text_input("Namespace (опционально)", "")
    if st.button("Получить статистику"):
        result = client.get_stats(collection=namespace or None)
        st.json(result)

st.divider()

st.subheader("Поиск")
query = st.text_input("Запрос", "")
top_k = st.slider("top_k", 1, 20, 5)
search_ns = st.text_input("Namespace (поиск)", "")
if st.button("Искать") and query:
    result = client.search(query, top_k, namespace=search_ns or None)
    st.json(result)

st.divider()

st.subheader("Загрузка (PDF / DOCX / MD / TXT)")
uploaded = st.file_uploader(
    "Документ", type=["pdf", "docx", "md", "txt"], accept_multiple_files=False
)
upload_ns = st.text_input("Namespace (загрузка)", "default")
upload_meta = st.text_area(
    "Metadata JSON (опционально)", '{"source": "streamlit"}', height=80
)
if st.button("Загрузить") and uploaded is not None:
    data: dict[str, str] = {"namespace": upload_ns}
    if upload_meta.strip():
        try:
            json.loads(upload_meta)
            data["metadata_json"] = upload_meta
        except json.JSONDecodeError:
            st.warning("metadata_json: невалидный JSON, передаю без metadata")
    result = client.upload(
        file_bytes=uploaded.getvalue(),
        filename=uploaded.name,
        content_type=uploaded.type,
        namespace=upload_ns,
        metadata_json=data.get("metadata_json"),
    )
    st.json(result)

st.divider()
st.subheader("Augment (с freshness badge)")
augment_query = st.text_input("Запрос для Augment", "", key="augment-q")
augment_top_k = st.slider("top_k (augment)", 1, 20, 5, key="augment-tk")
augment_ns = st.text_input("Namespace (расширение)", "", key="augment-ns")
max_staleness = st.number_input(
    "Максимальная устарелость (часы, 0=без фильтра)", min_value=0.0, value=72.0, step=24.0
)
if st.button("Дополнить") and augment_query:
    result = client.augment(
        augment_query, namespace=augment_ns or None, top_k=augment_top_k
    )
    worst = result.get("worst_freshness", "fresh")
    badge = {
        "fresh": ":green_circle: СВЕЖИЙ",
        "stale": ":yellow_circle: УСТАРЕВШИЙ",
        "expired": ":red_circle: ПРОСРОЧЕН",
    }.get(worst, worst)
    st.markdown(f"Свежесть: {badge}")
    st.json(result)

related_pages_footer("22_RAG_Консоль")
