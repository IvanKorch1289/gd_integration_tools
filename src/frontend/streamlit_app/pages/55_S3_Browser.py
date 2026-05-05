"""S3 Browser — просмотр бакетов и файлов в S3.

Позволяет:

* увидеть список бакетов и ключей (с префикс-фильтром);
* скачать файл через presigned URL;
* посмотреть содержимое текстовых файлов inline (до 1 МБ).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="S3 Browser", page_icon=":package:", layout="wide")
st.header(":package: S3 Browser")

client = get_api_client()

prefix = st.text_input("Префикс ключа", value="")

try:
    files = client._request(  # type: ignore[attr-defined]
        "GET", "/api/v1/storage/list", params={"prefix": prefix, "limit": 200}
    )
    if not isinstance(files, list):
        files = []
except Exception as exc:  # noqa: BLE001
    files = []
    st.error(f"Не удалось получить список файлов: {exc}")

if not files:
    st.info("Файлы не найдены или бакет пуст.")
else:
    st.caption(f"Найдено: {len(files)}")
    for item in files[:100]:
        key = item.get("key") or item.get("name") or "?"
        size = item.get("size", 0)
        modified = item.get("last_modified", "—")
        cols = st.columns([5, 2, 2, 2])
        cols[0].write(f"**{key}**")
        cols[1].write(f"{size} байт")
        cols[2].write(modified)
        if cols[3].button("Preview", key=f"prev_{key}"):
            try:
                content = client._request(
                    "GET", "/api/v1/storage/get", params={"key": key}
                )  # type: ignore[attr-defined]
                st.code(
                    content[:10_000]
                    if isinstance(content, str)
                    else str(content)[:10_000]
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ошибка preview: {exc}")
