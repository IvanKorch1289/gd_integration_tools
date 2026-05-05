"""Cache Explorer — просмотр и инвалидация Redis-кэша.

Использует admin-эндпоинты:

* ``GET /api/v1/admin/cache/keys?pattern=...`` — список ключей.
* ``GET /api/v1/admin/cache/{key}`` — значение + TTL.
* ``POST /api/v1/admin/cache/invalidate?pattern=...`` — точечная инвалидация.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Cache", page_icon=":package:", layout="wide")
st.header(":package: Cache Explorer")

client = get_api_client()

pattern = st.text_input(
    "Pattern поиска ключей", value="*", help="Glob-паттерн Redis (напр., `user:*`)"
)

try:
    keys = client._request(  # type: ignore[attr-defined]
        "GET", "/api/v1/admin/cache/keys", params={"pattern": pattern, "limit": 200}
    )
    if not isinstance(keys, list):
        keys = []
except Exception as exc:  # noqa: BLE001
    keys = []
    st.error(f"Не удалось получить ключи: {exc}")

st.caption(f"Найдено: {len(keys)}")

for key in keys[:100]:
    with st.expander(key):
        try:
            data = client._request("GET", f"/api/v1/admin/cache/{key}")  # type: ignore[attr-defined]
            st.json(data)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
        if st.button("Удалить", key=f"del_{key}"):
            try:
                client._request("DELETE", f"/api/v1/admin/cache/{key}")  # type: ignore[attr-defined]
                st.success("Удалено")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

st.divider()
st.subheader("Массовая инвалидация")
invalidate_pattern = st.text_input("Pattern для инвалидации", value="", key="inv_pat")
if st.button("Invalidate") and invalidate_pattern:
    try:
        resp = client._request(  # type: ignore[attr-defined]
            "POST",
            "/api/v1/admin/cache/invalidate",
            params={"pattern": invalidate_pattern},
        )
        st.success(f"Удалено: {resp}")
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))
