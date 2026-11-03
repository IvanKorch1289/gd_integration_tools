"""Audit Log — поиск по аудит-журналу с фильтрами периода.

Аудит пишется через :class:`AuditLogMiddleware` (audit_log.py). Эндпоинт
``GET /api/v1/audit/capability`` возвращает последние N записей audit-stream
в обратном хронологическом порядке. Серверных фильтров у него нет, поэтому
период/маршрут/пользователь/статус применяются локально (ADR-0422:
``GET /api/v1/admin/audit`` не существует → был 404).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

UTC = UTC

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    require_auth,
    setup_page,
)

setup_page(layout="wide", initial_sidebar_state="expanded")
require_auth(label="admin")
st.header(":mag: Журнал аудита")

client = get_api_client()

# ── Period filter
col1, col2 = st.columns(2)
dt_from = col1.date_input("С даты", value=datetime.now(UTC).date() - timedelta(days=1))
dt_to = col2.date_input("По дату", value=datetime.now(UTC).date())

col3, col4, col5 = st.columns(3)
route_filter = col3.text_input("Подстрока ID маршрута")
user_filter = col4.text_input("User ID")
status_filter = col5.selectbox("Status", ["all", "success", "error"])

params: dict[str, object] = {"count": 500}


def _apply_filters(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Локальная фильтрация audit-записей.

    ``GET /api/v1/audit/capability`` отдаёт только последние N записей без
    фильтров, поэтому период/маршрут/пользователь/статус применяются здесь.
    """
    result: list[dict[str, object]] = []
    for rec in records:
        stamp = str(rec.get("timestamp") or "")[:10]
        if stamp and not (dt_from.isoformat() <= stamp <= dt_to.isoformat()):
            continue
        if route_filter and route_filter not in str(rec.get("path") or ""):
            continue
        if user_filter and user_filter not in str(rec.get("user_id") or ""):
            continue
        code = rec.get("status_code")
        is_error = isinstance(code, int) and code >= 400
        if status_filter == "success" and is_error:
            continue
        if status_filter == "error" and not is_error:
            continue
        result.append(rec)
    return result


try:
    with st.spinner("Загрузка audit-логов..."):
        records = client._request("GET", "/api/v1/audit/capability", params=params)
    if not isinstance(records, list):
        records = []
    else:
        records = _apply_filters(records)
except Exception as exc:
    st.error(f"Ошибка: {exc}")
    records = []
    st.warning(f"Не удалось получить аудит: {exc}")

st.caption(f"Найдено: {len(records)}")

if records:
    st.dataframe(records, width="stretch", height=500)
else:
    st.info("Записей аудита не найдено. Измените фильтры или подождите новых событий.")

related_pages_footer("61_Журнал_аудита")
