"""Files S3 — Unified Storage Browser (S7 K5 + Sprint 7 Team T4).

Объединяет mock Object Browser и Unified Storage API.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page()
st.title("📁 Файлы S3 — Объектный браузер")
st.caption("S3/MinIO bucket файлы с preview/upload/download.")

# Mock buckets + objects
_MOCK_BUCKETS = ["credit-documents", "reports", "uploads-staging"]
_MOCK_OBJECTS: dict[str, list[dict[str, object]]] = {
    "credit-documents": [
        {
            "key": "skb/contracts/2026-05-01.pdf",
            "size_bytes": 234_567,
            "modified": "2026-05-01T10:23:45Z",
        },
        {
            "key": "skb/scoring/2026-05-15.json",
            "size_bytes": 12_456,
            "modified": "2026-05-15T08:00:00Z",
        },
        {
            "key": "nbki/reports/q1-2026.csv",
            "size_bytes": 1_234_567,
            "modified": "2026-05-12T14:30:00Z",
        },
    ],
    "reports": [
        {
            "key": "monthly/2026-04.xlsx",
            "size_bytes": 567_890,
            "modified": "2026-05-01T00:00:01Z",
        },
        {
            "key": "daily/2026-05-14.parquet",
            "size_bytes": 8_900_123,
            "modified": "2026-05-15T00:01:00Z",
        },
    ],
    "uploads-staging": [],
}

client = get_api_client()

tab_mock, tab_api = st.tabs(["Объектный браузер (Mock)", "Унифицированное хранилище"])

with tab_mock:
    st.subheader("Mock S3 Браузер")
    bucket = st.selectbox("Бакет", options=_MOCK_BUCKETS, index=0, key="mock_bucket")
    prefix = st.text_input(
        "Фильтр по префиксу", value="", placeholder="напр. skb/contracts/", key="mock_prefix"
    )
    uploaded = st.file_uploader(
        "Выбрать файл для upload",
        type=None,
        accept_multiple_files=False,
        key="mock_upload",
    )
    if uploaded is not None:
        target_key = st.text_input(
            "Целевой ключ (путь)",
            value=f"uploads-staging/{uploaded.name}",
            key="mock_target",
        )
        if st.button("Загрузить в S3", type="primary", key="mock_btn"):
            st.success(
                f"✓ Mock-upload: '{uploaded.name}' → '{bucket}/{target_key}' ({uploaded.size} bytes)"
            )

    def _filter_objects(bucket: str, prefix: str) -> list[dict[str, object]]:
        items = _MOCK_OBJECTS.get(bucket, [])
        if prefix:
            items = [o for o in items if str(o["key"]).startswith(prefix)]
        return items

    objects = _filter_objects(bucket, prefix)
    col1, col2, col3 = st.columns(3)
    col1.metric("Бакет", bucket)
    col2.metric("Объекты", len(objects))
    total_size = sum(int(o["size_bytes"]) for o in objects)
    col3.metric("Общий размер", f"{total_size / 1024:.1f} KB")

    st.subheader(f"Объекты в `s3://{bucket}/{prefix}`")
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
            width='stretch',
            hide_index=True,
        )
    else:
        st.info(f"Бакет `{bucket}` пустой или нет объектов по prefix `{prefix}`.")

    st.markdown("---")
    st.subheader("Предпросмотр / Скачать")
    if objects:
        selected_key = st.selectbox(
            "Объект", options=[str(o["key"]) for o in objects], index=0, key="mock_sel"
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
                "💾 Скачать",
                data=f"Mock content of {selected_key}".encode(),
                file_name=selected_key.split("/")[-1],
                mime="application/octet-stream",
                key="mock_dl",
            )

    st.caption(
        f"Последнее обновление: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )

with tab_api:
    st.header(":file_folder: Файлы унифицированного хранилища")
    st.caption(
        "Единый UI для S3 / MinIO / LocalFS. Provider выбирается на backend "
        "через `settings.storage.provider`."
    )

    st.subheader("Фильтры")
    api_bucket = st.text_input(
        "Бакет / корень",
        value="",
        help="Опционально — имя бакета (S3/MinIO) или поддиректория (LocalFS).",
        key="api_bucket",
    )
    api_prefix = st.text_input(
        "Префикс ключа",
        value="",
        help="Подстрока, с которой должен начинаться ключ.",
        key="api_prefix",
    )
    api_limit = st.number_input(
        "Лимит", min_value=10, max_value=1000, value=200, step=50, key="api_limit"
    )

    params: dict[str, object] = {"prefix": api_prefix, "limit": int(api_limit)}
    if api_bucket:
        params["bucket"] = api_bucket

    try:
        with st.spinner("Загрузка..."):
            items = client._request("GET", "/api/v1/storage/list", params=params)
        if not isinstance(items, list):
            items = []
    except Exception as exc:  # noqa: BLE001
        items = []
        st.error(f"Не удалось получить список файлов: {exc}")

    st.caption(f"Найдено: {len(items)}")

    if not items:
        st.info("Хранилище пустое или префикс не совпал ни с одним ключом.")
    else:
        for idx, item in enumerate(items):
            key = item.get("key") or item.get("name") or "?"
            size = item.get("size", 0)
            modified = item.get("last_modified", "—")
            cols = st.columns([5, 2, 2, 1, 1])
            cols[0].write(f"`{key}`")
            cols[1].write(f"{size} bytes")
            cols[2].write(modified)

            if cols[3].button("Предпросмотр", key=f"prev_{idx}_{key}"):
                try:
                    content = client._request(
                        "GET",
                        "/api/v1/storage/get",
                        params={
                            "key": key,
                            **({"bucket": api_bucket} if api_bucket else {}),
                        },
                    )
                    preview = (
                        content[:10_000]
                        if isinstance(content, str)
                        else str(content)[:10_000]
                    )
                    st.code(preview)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Предпросмотр не удался: {exc}")

            if cols[4].button("Скачать", key=f"dl_{idx}_{key}"):
                try:
                    resp = client._request(
                        "GET",
                        "/api/v1/storage/download",
                        params={
                            "key": key,
                            **({"bucket": api_bucket} if api_bucket else {}),
                        },
                    )
                    if isinstance(resp, dict) and "url" in resp:
                        st.markdown(f"[Скачать]({resp['url']})")
                    else:
                        st.download_button(
                            "Сохранить как файл",
                            data=resp if isinstance(resp, (bytes, str)) else str(resp),
                            file_name=key.rsplit("/", 1)[-1] or "file",
                            key=f"save_{idx}_{key}",
                        )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Скачивание не удалось: {exc}")

related_pages_footer("57_Файлы_S3")
