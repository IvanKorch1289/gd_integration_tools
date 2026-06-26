"""SQL Admin — безопасные read-only SELECT-запросы.

Запросы проходят через backend-эндпоинт ``POST /api/v1/admin/sql/query``,
который валидирует что это именно SELECT (без DML/DDL), проставляет LIMIT
и выполняет через ``session.execute(text(...))``. Все вызовы пишутся в аудит.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import require_auth, setup_page, related_pages_footer

setup_page(layout="wide", initial_sidebar_state="expanded")
require_auth(label="admin")
st.header(":floppy_disk: Консоль админа SQL")

st.warning(
    "Разрешены **только SELECT-запросы** с автоматическим LIMIT 1000. "
    "Все вызовы журналируются в аудит."
)

client = get_api_client()

default_query = "SELECT schemaname, tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
sql = st.text_area("SQL-запрос", value=default_query, height=180)
limit = st.number_input("Лимит (LIMIT)", min_value=1, max_value=10_000, value=1000, step=100)

if st.button("Выполнить", type="primary"):
    try:
        with st.spinner("Выполнение SQL..."):
            result = client._request(
            "POST", "/api/v1/admin/sql/query", json={"query": sql, "limit": int(limit)}
        )
        if isinstance(result, dict):
            rows = result.get("rows") or []
            columns = result.get("columns") or []
            st.caption(f"Строк: {len(rows)}, колонок: {len(columns)}")
            if rows:
                st.dataframe(rows, width='stretch', height=500)
            else:
                st.info("Запрос выполнен, но вернул 0 строк.")
            if result.get("error"):
                st.error(result["error"])
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))

related_pages_footer("64_SQL_Админ")
