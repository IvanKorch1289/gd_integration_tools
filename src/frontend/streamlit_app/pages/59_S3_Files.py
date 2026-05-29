"""Unified Storage Files Browser — S3 / MinIO / LocalFS (Sprint 7 Team T4).

Единый UI поверх ``/api/v1/storage/*`` endpoints (CLAUDE.md V15 §Архитектура
— multi-backend gateways: S3↔MinIO↔LocalFS). Бэкенд сам решает какой
provider использовать через
:func:`src.backend.infrastructure.storage.factory.get_object_storage`,
поэтому фронту достаточно одной страницы.

Возможности:

* выбор виртуального бакета/префикса (для LocalFS — поддиректория var/storage);
* листинг до 500 ключей;
* preview содержимого текстовых файлов (до 10 КБ);
* download через ``GET /api/v1/storage/download`` (presigned URL или
  inline-stream для LocalFS).

Архитектурно вызывает только публичный REST API (см.
:class:`src.frontend.streamlit_app.api_client.APIClient` и CLAUDE.md
ограничения слоёв).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="Storage Files", page_icon=":file_folder:", layout="wide")
st.header(":file_folder: Unified Storage Files")
st.caption(
    "Единый UI для S3 / MinIO / LocalFS. Provider выбирается на backend "
    "через `settings.storage.provider`."
)

client = get_api_client()

# ---------------------------------------------------------------------------
# Sidebar — фильтры
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Фильтры")
    bucket = st.text_input(
        "Bucket / root",
        value="",
        help="Опционально — имя бакета (S3/MinIO) или поддиректория (LocalFS).",
    )
    prefix = st.text_input(
        "Префикс ключа", value="", help="Подстрока, с которой должен начинаться ключ."
    )
    limit = st.number_input("Лимит", min_value=10, max_value=1000, value=200, step=50)

# ---------------------------------------------------------------------------
# Листинг
# ---------------------------------------------------------------------------
params: dict[str, object] = {"prefix": prefix, "limit": int(limit)}
if bucket:
    params["bucket"] = bucket

try:
    items = client._request("GET", "/api/v1/storage/list", params=params)  # type: ignore[attr-defined]
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

        if cols[3].button("Preview", key=f"prev_{idx}_{key}"):
            try:
                content = client._request(  # type: ignore[attr-defined]
                    "GET",
                    "/api/v1/storage/get",
                    params={"key": key, **({"bucket": bucket} if bucket else {})},
                )
                preview = (
                    content[:10_000]
                    if isinstance(content, str)
                    else str(content)[:10_000]
                )
                st.code(preview)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Preview failed: {exc}")

        if cols[4].button("Download", key=f"dl_{idx}_{key}"):
            try:
                resp = client._request(  # type: ignore[attr-defined]
                    "GET",
                    "/api/v1/storage/download",
                    params={"key": key, **({"bucket": bucket} if bucket else {})},
                )
                if isinstance(resp, dict) and "url" in resp:
                    st.markdown(f"[Скачать]({resp['url']})")
                else:
                    st.download_button(
                        "Save as file",
                        data=resp if isinstance(resp, (bytes, str)) else str(resp),
                        file_name=key.rsplit("/", 1)[-1] or "file",
                        key=f"save_{idx}_{key}",
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Download failed: {exc}")
