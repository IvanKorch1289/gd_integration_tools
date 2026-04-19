"""Orders — CRUD заказов."""

import json
import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.entrypoints.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Orders", page_icon=":package:", layout="wide")
st.header("Orders")

client = get_api_client()

# ──────────── Таблица заказов ────────────

try:
    orders = client.get_orders()
    if isinstance(orders, dict) and "items" in orders:
        items = orders["items"]
    elif isinstance(orders, list):
        items = orders
    else:
        items = []
except Exception as exc:
    st.error(f"Ошибка загрузки заказов: {exc}")
    items = []

if items:
    st.dataframe(items, use_container_width=True)
else:
    st.info("Нет заказов.")

# ──────────── Создание заказа ────────────

with st.expander("Создать заказ"):
    with st.form("create_order", clear_on_submit=True):
        pledge_gd_id = st.number_input("Pledge GD ID", min_value=1, step=1)
        order_kind_id = st.number_input("Order Kind ID", min_value=1, step=1)

        if st.form_submit_button("Создать"):
            try:
                result = client.create_order({
                    "pledge_gd_id": int(pledge_gd_id),
                    "order_kind_id": int(order_kind_id),
                })
                st.success(f"Заказ создан: {result}")
                st.rerun()
            except Exception as exc:
                st.error(f"Ошибка: {exc}")

# ──────────── Удаление заказа ────────────

with st.expander("Удалить заказ"):
    order_id = st.number_input("ID заказа для удаления", min_value=1, step=1, key="delete_id")
    if st.button("Удалить"):
        try:
            client.delete_order(int(order_id))
            st.success(f"Заказ {order_id} удалён.")
            st.rerun()
        except Exception as exc:
            st.error(f"Ошибка: {exc}")
