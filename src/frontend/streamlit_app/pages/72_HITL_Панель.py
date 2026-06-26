"""HITL Panel — Human-in-the-Loop approval (Sprint 9 K5 W2).

Список pending HITL signals, действия approve/reject/request_info.
Использует st.fragment для real-time refresh без перезагрузки страницы.

Feature-flag: ``feature_flags.hitl_panel_enabled`` (default-OFF).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import require_auth, setup_page

setup_page()
require_auth(label="write action")
st.header(":busts_in_silhouette: HITL-панель согласования")

client = get_api_client()

with st.sidebar:
    st.subheader("Фильтр")
    tenant_filter = st.text_input("Tenant ID (опц.)", value="")
    auto_refresh = st.toggle("Авто-обновление каждые 5s", value=False)


def _fetch_pending(tenant: str | None) -> list[dict]:
    params: dict[str, str] = {}
    if tenant:
        params["tenant_id"] = tenant
    try:
        response = client.get("/hitl/pending", params=params)
        response.raise_for_status()
        return response.json().get("items", [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить pending-сигналы: {exc}")
        return []


@st.fragment(run_every=5 if "auto_refresh" not in st.session_state else None)
def render_pending_table() -> None:
    """Таблица с автообновлением в реальном времени."""
    pending = _fetch_pending(tenant_filter or None)
    if not pending:
        st.info("Нет pending HITL signals в выбранном tenant.")
        return

    st.metric("Pending-сигналов", len(pending))
    for signal in pending:
        with st.expander(
            f":hourglass: {signal['title']} — workflow {signal['workflow_id']}",
            expanded=False,
        ):
            col_left, col_right = st.columns([2, 1])
            with col_left:
                st.json(signal["payload"], expanded=False)
                st.caption(
                    f"Создан: {signal['created_at']} | "
                    f"Инициатор: {signal['initiator']}"
                )
            with col_right:
                operator = st.text_input(
                    "Оператор (ваше имя)",
                    value=st.session_state.get("operator_name", ""),
                    key=f"op-{signal['signal_id']}",
                )
                comment = st.text_area(
                    "Комментарий", value="", key=f"comment-{signal['signal_id']}", height=80
                )
                col_a, col_b, col_c = st.columns(3)
                if col_a.button(
                    ":white_check_mark: Approve", key=f"appr-{signal['signal_id']}"
                ):
                    _resolve(signal["signal_id"], "approve", operator, comment)
                if col_b.button(":x: Reject", key=f"rej-{signal['signal_id']}"):
                    _resolve(signal["signal_id"], "reject", operator, comment)
                if col_c.button(
                    ":mag: Запросить инфо", key=f"info-{signal['signal_id']}"
                ):
                    _resolve(signal["signal_id"], "request_info", operator, comment)


def _resolve(signal_id: str, action: str, operator: str, comment: str) -> None:
    if not operator.strip():
        st.warning("Заполните поле «Оператор (ваше имя)»")
        return
    try:
        response = client.post(
            f"/hitl/{signal_id}/resolve",
            json={
                "action": action,
                "resolved_by": operator.strip(),
                "comment": comment.strip() or None,
            },
        )
        response.raise_for_status()
        st.success(f"Сигнал {signal_id} обработан: {action}")
        st.session_state["operator_name"] = operator.strip()
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось обработать: {exc}")


render_pending_table()


# ──────────────────────── Sprint 12 K5 W2: History ─────────────
st.divider()
st.subheader("📜 HITL History")
st.caption(
    "Историческая запись HITL decisions из workflow_audit "
    "(hitl.approved/rejected/requested_info events)."
)

col_h1, col_h2, col_h3, col_h4 = st.columns(4)
hist_tenant = col_h1.text_input("Фильтр tenant", key="hist_tenant")
hist_action = col_h2.selectbox(
    "Фильтр действия",
    options=["", "approve", "reject", "request_info"],
    key="hist_action",
)
hist_operator = col_h3.text_input("Фильтр оператора", key="hist_op")
hist_limit = col_h4.number_input("Лимит", min_value=10, max_value=1000, value=100)

if st.button("Загрузить историю", type="primary"):
    try:
        params: dict = {"limit": int(hist_limit)}
        if hist_tenant:
            params["tenant_id"] = hist_tenant
        if hist_action:
            params["action"] = hist_action
        if hist_operator:
            params["operator"] = hist_operator
        resp = client.get("/hitl/history", params=params)
        resp.raise_for_status()
        body = resp.json()
        items = body.get("items", [])
        if not items:
            st.info("Нет записей по выбранным фильтрам.")
        else:
            st.write(f"Найдено: {len(items)}")
            st.dataframe(items)

            try:
                import io

                import pandas as pd

                df = pd.DataFrame(items)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                st.download_button(
                    "Экспорт CSV",
                    csv_buffer.getvalue(),
                    file_name="hitl_history.csv",
                    mime="text/csv",
                )
            except ImportError:
                pass
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось загрузить историю: {exc}")
