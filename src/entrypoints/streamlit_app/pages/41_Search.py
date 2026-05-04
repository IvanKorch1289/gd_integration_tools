"""Streamlit-страница единого поиска (Wave 9.3.3).

Поверх ``/api/v1/search/{logs|orders|notebooks}``. UI работает даже
если индексы пусты — возвращается пустой массив.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import streamlit as st

API_BASE = st.session_state.get("api_base", "http://localhost:8000/api/v1")


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _get(path: str, **params: Any) -> list[dict[str, Any]] | dict[str, Any]:
    url = f"{API_BASE}/search{path}"
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=clean)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка запроса: {exc}")
        return []


st.set_page_config(page_title="Search", page_icon="🔎", layout="wide")
st.title("🔎 Search")
st.caption("Единый поиск по audit-логам, заказам и notebooks (Elasticsearch).")

q = st.text_input("Запрос", value=st.session_state.get("search_q", ""))
st.session_state["search_q"] = q

tab_logs, tab_orders, tab_notebooks, tab_agg = st.tabs(
    ["Логи", "Заказы", "Notebooks", "Агрегации"]
)

with tab_logs:
    col1, col2, col3 = st.columns(3)
    with col1:
        entity_type = st.text_input("entity_type", value="", key="logs_entity")
    with col2:
        tenant_id = st.text_input("tenant_id", value="", key="logs_tenant")
    with col3:
        limit = st.number_input("limit", value=20, min_value=1, max_value=200)
    rows = _run(
        _get(
            "/logs",
            q=q or None,
            entity_type=entity_type or None,
            tenant_id=tenant_id or None,
            limit=int(limit),
        )
    )
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("Ничего не найдено или индекс пуст.")

with tab_orders:
    col1, col2 = st.columns(2)
    with col1:
        status = st.text_input("status", value="", key="orders_status")
    with col2:
        limit = st.number_input(
            "limit", value=20, min_value=1, max_value=200, key="orders_limit"
        )
    rows = _run(_get("/orders", q=q or None, status=status or None, limit=int(limit)))
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("Ничего не найдено или индекс пуст.")

with tab_notebooks:
    col1, col2 = st.columns(2)
    with col1:
        tag = st.text_input("tag", value="", key="notebooks_tag")
    with col2:
        limit = st.number_input(
            "limit", value=20, min_value=1, max_value=200, key="notebooks_limit"
        )
    rows = _run(_get("/notebooks", q=q or None, tag=tag or None, limit=int(limit)))
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("Ничего не найдено или индекс пуст.")

with tab_agg:
    col1, col2, col3 = st.columns(3)
    with col1:
        index = st.selectbox("Индекс", options=["audit_logs", "orders", "notebooks"])
    with col2:
        field = st.text_input("Поле для terms", value="entity_type")
    with col3:
        size = st.number_input("size", value=10, min_value=1, max_value=100)
    if st.button("Посчитать"):
        result = _run(
            _get("/aggregations", index=index, field=field, q=q or None, size=int(size))
        )
        st.json(result)
