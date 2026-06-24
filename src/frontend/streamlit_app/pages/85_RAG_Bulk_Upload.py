"""Streamlit-страница 85 — RAG Bulk Upload (S19 K4 W1).

Поддерживает:
* Drag-drop файлы (.txt, .md, .json) — каждый файл как отдельный документ.
* Textarea для ввода JSON массива документов {content, metadata}.
* Выбор namespace (collection).
* Вызов POST /api/v1/rag/bulk-ingest.

Feature flag: FEATURE_MULTIPART_RAG_INGEST должен быть включён.
"""

from __future__ import annotations

import json

import streamlit as st

from src.frontend.streamlit_app.api_clients import K4APIClient
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("RAG Bulk Upload", "📤")
st.title("📤 RAG — массовая загрузка в RAG")

FEATURE_FLAG_NAME = "multipart_rag_ingest"


def _check_feature_flag() -> bool:
    """Проверяет feature flag multipart_rag_ingest через API."""
    client = K4APIClient()
    try:
        flags = client._request("GET", "/api/v1/admin/feature-flags")
        if isinstance(flags, dict):
            return bool(flags.get(FEATURE_FLAG_NAME, False))
        return False
    except Exception:  # noqa: BLE001
        return False


if not _check_feature_flag():
    st.error(
        f"⚠️ Feature flag `{FEATURE_FLAG_NAME}` выключен. "
        "Для активации установите `FEATURE_MULTIPART_RAG_INGEST=true`."
    )
    st.stop()

client = K4APIClient()

tab_file, tab_json = st.tabs(["📁 File Upload", "📝 JSON Input"])

# ─── Tab 1: File Upload ──────────────────────────────────────────────────────

with tab_file:
    st.subheader("Drag & Drop или выбор файлов")
    st.caption("Каждый файл → один документ с {content, metadata}.")
    uploaded_files = st.file_uploader(
        "Поддерживаемые форматы: .txt, .md, .json",
        type=["txt", "md", "json"],
        accept_multiple_files=True,
        help="Перетащите файлы сюда или кликните для выбора",
    )

    file_collection = st.text_input(
        "Collection (namespace)", value="default", key="file_ns"
    )

    if uploaded_files:
        st.write(f"**Выбрано файлов:** {len(uploaded_files)}")
        for f in uploaded_files:
            st.write(
                f"  • `{getattr(f, 'name', 'unnamed')}` ({getattr(f, 'size', '?')} bytes)"
            )

        if st.button("Загрузить файлы", type="primary", key="ingest_files"):
            documents = []
            for f in uploaded_files:
                try:
                    content = f.read().decode("utf-8", errors="replace")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка чтения {getattr(f, 'name', 'file')}: {exc}")
                    continue

                filename = getattr(f, "name", "unknown")
                metadata = {"source": "bulk_upload", "filename": filename}
                documents.append({"content": content, "metadata": metadata})

            if documents:
                with st.spinner("Загрузка..."):
                    try:
                        result = client._request(
                            "POST",
                            "/api/v1/rag/bulk-ingest",
                            json={
                                "documents": documents,
                                "collection": file_collection,
                            },
                        )
                        st.success("Массовая загрузка завершена!")
                        st.json(result)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Ошибка загрузки: {exc}")

# ─── Tab 2: JSON Input ───────────────────────────────────────────────────────

with tab_json:
    st.subheader("JSON массив документов")
    st.caption("Вставьте JSON массив объектов {content, metadata}")

    default_json = json.dumps(
        [
            {
                "content": "Первый тестовый документ для RAG.",
                "metadata": {"source": "manual", "type": "test"},
            },
            {
                "content": "Второй тестовый документ.",
                "metadata": {"source": "manual", "type": "test"},
            },
        ],
        ensure_ascii=False,
        indent=2,
    )

    json_input = st.text_area(
        "Documents JSON",
        value=default_json,
        height=300,
        help="JSON массив документов с полями content (str) и metadata (dict, опционально)",
    )

    json_collection = st.text_input(
        "Collection (namespace)", value="default", key="json_ns"
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        parse_btn = st.button("Проверить JSON", type="secondary")
    with col2:
        ingest_btn = st.button("Загрузить JSON", type="primary")

    if parse_btn:
        try:
            parsed = json.loads(json_input)
            if isinstance(parsed, list):
                st.success(f"✓ Valid JSON array ({len(parsed)} documents)")
                for i, doc in enumerate(parsed):
                    if not isinstance(doc, dict):
                        st.error(f"Document {i}: not a dict")
                    elif "content" not in doc:
                        st.warning(f"Document {i}: missing 'content' field")
                    else:
                        st.write(f"  Document {i}: {doc.get('content', '')[:60]}...")
            else:
                st.error("Input must be a JSON array (list), not a single object")
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")

    if ingest_btn:
        try:
            documents = json.loads(json_input)
            if not isinstance(documents, list):
                st.error("Входные данные должны быть JSON-массивом документов")
            elif len(documents) == 0:
                st.error("Массив пуст")
            else:
                with st.spinner("Загрузка..."):
                    try:
                        result = client._request(
                            "POST",
                            "/api/v1/rag/bulk-ingest",
                            json={
                                "documents": documents,
                                "collection": json_collection,
                            },
                        )
                        st.success("Массовая загрузка завершена!")
                        st.json(result)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Ошибка загрузки: {exc}")
        except json.JSONDecodeError as exc:
            st.error(f"JSON decode error: {exc}")

# ─── Status Section ─────────────────────────────────────────────────────────

st.divider()
st.subheader("Последние задачи ingest")
if st.button("Обновить статус", key="refresh_status"):
    try:
        recent = client._request(
            "GET", "/api/v1/rag/ingest/recent", params={"limit": 5}
        )
        items = recent.get("items", [])
        if items:
            for item in items:
                with st.expander(
                    f"Task: {item.get('task_id', '?')[:8]}... — {item.get('status', '?')}"
                ):
                    st.json(item)
        else:
            st.info("Нет последних задач ingest.")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not fetch recent tasks: {exc}")
