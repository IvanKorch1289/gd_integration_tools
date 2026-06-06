"""SQL Admin — безопасные read-only SELECT-запросы.

Запросы проходят через backend-эндпоинт ``POST /api/v1/admin/sql/query``,
который валидирует что это именно SELECT (без DML/DDL), проставляет LIMIT
и выполняет через ``session.execute(text(...))``. Все вызовы пишутся в аудит.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page(
    'SQL',
    ':floppy_disk:',
    layout='wide',
    initial_sidebar_state='expanded',
)
st.header(":floppy_disk: SQL Admin Console")

st.warning(
    "Разрешены **только SELECT-запросы** с автоматическим LIMIT 1000. "
    "Все вызовы журналируются в аудит."
)

client = get_api_client()

default_query = "SELECT schemaname, tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
sql = st.text_area("SQL", value=default_query, height=180)
limit = st.number_input("LIMIT", min_value=1, max_value=10_000, value=1000, step=100)

if st.button("Выполнить", type="primary"):
    try:
        result = client._request(
            "POST", "/api/v1/admin/sql/query", json={"query": sql, "limit": int(limit)}
        )
        if isinstance(result, dict):
            rows = result.get("rows") or []
            columns = result.get("columns") or []
            st.caption(f"Строк: {len(rows)}, колонок: {len(columns)}")
            if rows:
                st.dataframe(rows, use_container_width=True, height=500)
            if result.get("error"):
                st.error(result["error"])
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))
