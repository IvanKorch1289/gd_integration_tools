"""Audit Log — поиск по аудит-журналу с фильтрами периода.

Аудит пишется через :class:`AuditLogMiddleware` (audit_log.py). Эндпоинт
``GET /api/v1/admin/audit`` возвращает записи в обратном хронологическом
порядке; фильтры — ``from``/``to`` (ISO-datetime), ``route``, ``user_id``,
``status``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Audit", page_icon=":mag:", layout="wide")
st.header(":mag: Audit Log")

client = get_api_client()

# ── Period filter
col1, col2 = st.columns(2)
dt_from = col1.date_input("С даты", value=datetime.utcnow().date() - timedelta(days=1))
dt_to = col2.date_input("По дату", value=datetime.utcnow().date())

col3, col4, col5 = st.columns(3)
route_filter = col3.text_input("Route ID substring")
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
    records = client._request("GET", "/api/v1/admin/audit", params=params)  # type: ignore[attr-defined]
    if not isinstance(records, list):
        records = []
except Exception as exc:  # noqa: BLE001
    records = []
    st.warning(f"Не удалось получить аудит: {exc}")

st.caption(f"Найдено: {len(records)}")

if records:
    st.dataframe(records, use_container_width=True, height=500)
