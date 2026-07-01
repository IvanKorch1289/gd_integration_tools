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


def _emit_crud_event(
    *,
    action: str,
    outcome: str,
    target: str,
    extra: dict | None = None,
) -> None:
    """S175 M10.2: structured audit-event для CRUD operations.

    Lazy-import ``emit_audit_safe`` (dev-envs без DI не сломаются).
    Graceful fallback (warning log).
    """
    try:
        from src.backend.core.frontend_facade import emit_audit_safe

        details: dict = {
            "page_key": "10_Заказы",
            "action": action,
            "outcome": outcome,
            "target": target,
        }
        if extra:
            details.update(extra)
        emit_audit_safe(
            event=f"frontend.crud.{action}",
            action=f"crud.{action}",
            outcome=("success" if outcome == "success" else "failure"),
            details=details,
            severity=("info" if outcome == "success" else "warning"),
        )
    except Exception as _exc:  # pragma: no cover
        import logging as _logging

        _logging.getLogger("frontend.pages.10_Заказы").debug(
            "frontend.crud.%s: audit-event emit failed: %s", action, _exc
        )


with st.expander("Создать заказ"), st.form("create_order", clear_on_submit=True):
    pledge_gd_id = st.number_input("ID заявки GD", min_value=1, step=1)
    order_kind_id = st.number_input("ID вида заказа", min_value=1, step=1)

    if st.form_submit_button("Создать"):
        target = f"pledge_gd_id={int(pledge_gd_id)},order_kind_id={int(order_kind_id)}"
        try:
            result = client.create_order(
                {
                    "pledge_gd_id": int(pledge_gd_id),
                    "order_kind_id": int(order_kind_id),
                }
            )
            st.success(f"Заказ создан: {result}")
            _emit_crud_event(
                action="create_order",
                outcome="success",
                target=target,
                extra={"result": str(result)},
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Ошибка: {exc}")
            _emit_crud_event(
                action="create_order",
                outcome="failure",
                target=target,
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )

# ──────────── Удаление заказа ────────────

with st.expander("Удалить заказ"):
    order_id = st.number_input(
        "ID заказа для удаления", min_value=1, step=1, key="delete_id"
    )
    if st.button("Удалить"):
        target = f"order_id={int(order_id)}"
        try:
            client.delete_order(int(order_id))
            st.success(f"Заказ {order_id} удалён.")
            _emit_crud_event(
                action="delete_order",
                outcome="success",
                target=target,
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Ошибка: {exc}")
            _emit_crud_event(
                action="delete_order",
                outcome="failure",
                target=target,
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )

related_pages_footer("10_Заказы")
