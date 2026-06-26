"""Orders — CRUD заказов."""

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    require_auth,
    setup_page,
)

setup_page(layout="wide", initial_sidebar_state="expanded")
require_auth(label="write action")
st.header("Заказы")
st.caption("CRUD заказов: просмотр списка, создание и удаление.")

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
    st.dataframe(items, width='stretch')
else:
    st.info("Нет заказов.")

# ──────────── Создание заказа ────────────

with st.expander("Создать заказ"), st.form("create_order", clear_on_submit=True):
    pledge_gd_id = st.number_input("ID заявки GD", min_value=1, step=1)
    order_kind_id = st.number_input("ID вида заказа", min_value=1, step=1)

    if st.form_submit_button("Создать"):
        try:
            result = client.create_order(
                {
                    "pledge_gd_id": int(pledge_gd_id),
                    "order_kind_id": int(order_kind_id),
                }
            )
            st.success(f"Заказ создан: {result}")
            st.rerun()
        except Exception as exc:
            st.error(f"Ошибка: {exc}")

# ──────────── Удаление заказа ────────────

with st.expander("Удалить заказ"):
    order_id = st.number_input(
        "ID заказа для удаления", min_value=1, step=1, key="delete_id"
    )
    if st.button("Удалить"):
        try:
            client.delete_order(int(order_id))
            st.success(f"Заказ {order_id} удалён.")
            st.rerun()
        except Exception as exc:
            st.error(f"Ошибка: {exc}")

related_pages_footer("10_Заказы")
