"""Streamlit-страница Files S3 (S7 K5).

Назначение:
    Browser для S3/MinIO bucket — список объектов с пагинацией +
    preview (text/json/csv) + upload/download.

Источник данных:
    REST ``/api/v1/admin/files/*`` через ``aiobotocore``/``minio``. Mock
    fallback при отсутствии backend.

feature_flag: ``s3_files_ui_enabled`` (default-OFF).
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

st.set_page_config(page_title="Files S3", page_icon="📁", layout="wide")
st.title("📁 Files S3 — Object Browser")
st.caption("Sprint 7 K5 — S3/MinIO bucket файлы с preview/upload/download.")

# Mock buckets + objects
_MOCK_BUCKETS = ["credit-documents", "reports", "uploads-staging"]
_MOCK_OBJECTS: dict[str, list[dict[str, object]]] = {
    "credit-documents": [
        {"key": "skb/contracts/2026-05-01.pdf", "size_bytes": 234_567, "modified": "2026-05-01T10:23:45Z"},
        {"key": "skb/scoring/2026-05-15.json", "size_bytes": 12_456, "modified": "2026-05-15T08:00:00Z"},
        {"key": "nbki/reports/q1-2026.csv", "size_bytes": 1_234_567, "modified": "2026-05-12T14:30:00Z"},
    ],
    "reports": [
        {"key": "monthly/2026-04.xlsx", "size_bytes": 567_890, "modified": "2026-05-01T00:00:01Z"},
        {"key": "daily/2026-05-14.parquet", "size_bytes": 8_900_123, "modified": "2026-05-15T00:01:00Z"},
    ],
    "uploads-staging": [],
}

# Sidebar — bucket + path filter
with st.sidebar:
    st.header("Bucket / Path")
    bucket = st.selectbox("Bucket", options=_MOCK_BUCKETS, index=0)
    prefix = st.text_input("Prefix filter", value="", placeholder="напр. skb/contracts/")
    st.markdown("---")
    st.header("Upload new object")
    uploaded = st.file_uploader("Выбрать файл", type=None, accept_multiple_files=False)
    if uploaded is not None:
        target_key = st.text_input("Target key (path)", value=f"uploads-staging/{uploaded.name}")
        if st.button("Загрузить в S3", type="primary"):
            st.success(f"✓ Mock-upload: '{uploaded.name}' → '{bucket}/{target_key}' ({uploaded.size} bytes)")

# Main: list objects
def _filter_objects(bucket: str, prefix: str) -> list[dict[str, object]]:
    """Возвращает объекты bucket с фильтрацией по prefix."""
    items = _MOCK_OBJECTS.get(bucket, [])
    if prefix:
        items = [o for o in items if str(o["key"]).startswith(prefix)]
    return items


objects = _filter_objects(bucket, prefix)

col1, col2, col3 = st.columns(3)
col1.metric("Bucket", bucket)
col2.metric("Objects", len(objects))
total_size = sum(int(o["size_bytes"]) for o in objects)
col3.metric("Total size", f"{total_size / 1024:.1f} KB")

st.subheader(f"Objects in `s3://{bucket}/{prefix}`")
if objects:
    st.dataframe(
        [
            {
                "key": o["key"],
                "size_bytes": o["size_bytes"],
                "size_kb": f"{int(o['size_bytes']) / 1024:.1f} KB",
                "modified": o["modified"],
            }
            for o in objects
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info(f"Bucket `{bucket}` пустой или нет объектов по prefix `{prefix}`.")

# Preview/download
st.markdown("---")
st.subheader("Preview / Download")
if objects:
    selected_key = st.selectbox(
        "Объект",
        options=[str(o["key"]) for o in objects],
        index=0,
    )
    col_a, col_b = st.columns([3, 1])
    with col_a:
        if selected_key.endswith((".txt", ".json", ".csv", ".yaml", ".yml")):
            st.code(
                f"# Mock preview {selected_key}\n"
                f"# (текстовый preview доступен для text/json/csv/yaml)\n"
                f'{{"mock": true, "key": "{selected_key}", "bucket": "{bucket}"}}',
                language="json" if selected_key.endswith(".json") else "text",
            )
        else:
            st.info("Binary-объект: preview не доступен. Используйте download.")
    with col_b:
        st.download_button(
            "💾 Download",
            data=f"Mock content of {selected_key}".encode(),
            file_name=selected_key.split("/")[-1],
            mime="application/octet-stream",
        )

st.caption(f"Last refresh: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
