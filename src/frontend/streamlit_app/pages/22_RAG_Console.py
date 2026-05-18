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


st.divider()
st.subheader("Augment (с freshness badge)")
augment_query = st.text_input("Augment query", "", key="augment-q")
augment_top_k = st.slider("top_k (augment)", 1, 20, 5, key="augment-tk")
augment_ns = st.text_input("Namespace (augment)", "", key="augment-ns")
max_staleness = st.number_input(
    "Max staleness (hours, 0=без фильтра)",
    min_value=0.0,
    value=72.0,
    step=24.0,
)
if st.button("Augment") and augment_query:
    body_a: dict[str, object] = {
        "query": augment_query,
        "top_k": augment_top_k,
    }
    if augment_ns:
        body_a["namespace"] = augment_ns
    if max_staleness > 0:
        body_a["max_staleness_hours"] = max_staleness
    try:
        resp = httpx.post(
            f"{api_base}/api/v1/rag/augment", json=body_a, timeout=15.0
        )
        data_a = resp.json()
        worst = data_a.get("worst_freshness", "fresh")
        badge = {
            "fresh": ":green_circle: FRESH",
            "stale": ":yellow_circle: STALE",
            "expired": ":red_circle: EXPIRED",
        }.get(worst, worst)
        st.metric("Freshness", badge)
        dist = data_a.get("freshness_distribution", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("Fresh chunks", dist.get("fresh", 0))
        c2.metric("Stale chunks", dist.get("stale", 0))
        c3.metric("Expired (skipped)", data_a.get("skipped_expired", 0))
        with st.expander("Augment details"):
            st.json(data_a)
    except Exception as exc:  # noqa: BLE001
        st.error(f"augment failed: {exc}")
