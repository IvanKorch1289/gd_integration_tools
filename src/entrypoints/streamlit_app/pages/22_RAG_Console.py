"""RAG Console — UI для управления RAG (Wave 10.1).

Позволяет:
* посмотреть `/api/v1/rag/stats` (опционально по namespace);
* выполнить семантический поиск ``/api/v1/rag/search``;
* загрузить документ через multipart ``/api/v1/rag/upload``.
"""

from __future__ import annotations

import json

import httpx
import streamlit as st

st.set_page_config(page_title="RAG Console", layout="wide")

st.title("RAG Console")

api_base = st.text_input("API base URL", value="http://localhost:8000")

with st.expander("Статус RAG"):
    namespace = st.text_input("Namespace (опционально)", "")
    if st.button("Get stats"):
        params: dict[str, str] = {}
        if namespace:
            params["collection"] = namespace
        try:
            resp = httpx.get(f"{api_base}/api/v1/rag/stats", params=params, timeout=5.0)
            st.json(resp.json())
        except Exception as exc:  # noqa: BLE001
            st.error(f"stats failed: {exc}")

st.divider()

st.subheader("Поиск")
query = st.text_input("Query", "")
top_k = st.slider("top_k", 1, 20, 5)
search_ns = st.text_input("Namespace (search)", "")
if st.button("Search") and query:
    body: dict[str, object] = {"query": query, "top_k": top_k}
    if search_ns:
        body["namespace"] = search_ns
    try:
        resp = httpx.post(f"{api_base}/api/v1/rag/search", json=body, timeout=10.0)
        st.json(resp.json())
    except Exception as exc:  # noqa: BLE001
        st.error(f"search failed: {exc}")

st.divider()

st.subheader("Upload (PDF / DOCX / MD / TXT)")
uploaded = st.file_uploader(
    "Документ", type=["pdf", "docx", "md", "txt"], accept_multiple_files=False
)
upload_ns = st.text_input("Namespace (upload)", "default")
upload_meta = st.text_area(
    "Metadata JSON (опционально)", '{"source": "streamlit"}', height=80
)
if st.button("Upload") and uploaded is not None:
    files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type)}
    data: dict[str, str] = {"namespace": upload_ns}
    if upload_meta.strip():
        try:
            json.loads(upload_meta)
            data["metadata_json"] = upload_meta
        except json.JSONDecodeError:
            st.warning("metadata_json: невалидный JSON, передаю без metadata")
    try:
        resp = httpx.post(
            f"{api_base}/api/v1/rag/upload", files=files, data=data, timeout=60.0
        )
        st.json(resp.json())
    except Exception as exc:  # noqa: BLE001
        st.error(f"upload failed: {exc}")
