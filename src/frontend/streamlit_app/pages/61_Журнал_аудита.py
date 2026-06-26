"""Audit Log — поиск по аудит-журналу с фильтрами периода.

Аудит пишется через :class:`AuditLogMiddleware` (audit_log.py). Эндпоинт
``GET /api/v1/admin/audit`` возвращает записи в обратном хронологическом
порядке; фильтры — ``from``/``to`` (ISO-datetime), ``route``, ``user_id``,
``status``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc

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

params: dict[str, object] = {
    "from": f"{dt_from}T00:00:00",
    "to": f"{dt_to}T23:59:59",
    "limit": 200,
}
if route_filter:
    params["route"] = route_filter
if user_filter:
    params["user_id"] = user_filter
if status_filter != "all":
    params["status"] = status_filter

try:
    with st.spinner("Загрузка audit-логов..."):
        records = client._request("GET", "/api/v1/admin/audit", params=params)
    if not isinstance(records, list):
        records = []
except Exception as exc:  # noqa: BLE001
    records = []
    st.warning(f"Не удалось получить аудит: {exc}")

st.caption(f"Найдено: {len(records)}")

if records:
    st.dataframe(records, width='stretch', height=500)
else:
    st.info("Записей аудита не найдено. Измените фильтры или подождите новых событий.")

related_pages_footer("61_Журнал_аудита")
