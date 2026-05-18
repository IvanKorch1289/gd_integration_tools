"""HITL Panel — Human-in-the-Loop approval (Sprint 9 K5 W2).

Список pending HITL signals, действия approve/reject/request_info.
Использует st.fragment для real-time refresh без перезагрузки страницы.

Feature-flag: ``feature_flags.hitl_panel_enabled`` (default-OFF).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(
    page_title="HITL Panel", page_icon=":busts_in_silhouette:", layout="wide"
)
st.header(":busts_in_silhouette: HITL Approval Panel")

client = get_api_client()

with st.sidebar:
    st.subheader("Filter")
    tenant_filter = st.text_input("Tenant ID (опц.)", value="")
    auto_refresh = st.toggle("Auto-refresh каждые 5s", value=False)


def _fetch_pending(tenant: str | None) -> list[dict]:
    params: dict[str, str] = {}
    if tenant:
        params["tenant_id"] = tenant
    try:
        response = client.get("/hitl/pending", params=params)
        response.raise_for_status()
        return response.json().get("items", [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch pending signals: {exc}")
        return []


@st.fragment(run_every=5 if "auto_refresh" not in st.session_state else None)
def render_pending_table() -> None:
    """Real-time refresh table."""
    pending = _fetch_pending(tenant_filter or None)
    if not pending:
        st.info("Нет pending HITL signals в выбранном tenant.")
        return

    st.metric("Pending signals", len(pending))
    for signal in pending:
        with st.expander(
            f":hourglass: {signal['title']} — workflow {signal['workflow_id']}",
            expanded=False,
        ):
            col_left, col_right = st.columns([2, 1])
            with col_left:
                st.json(signal["payload"], expanded=False)
                st.caption(
                    f"Created: {signal['created_at']} | "
                    f"Initiator: {signal['initiator']}"
                )
            with col_right:
                operator = st.text_input(
                    "Operator (your name)",
                    value=st.session_state.get("operator_name", ""),
                    key=f"op-{signal['signal_id']}",
                )
                comment = st.text_area(
                    "Comment",
                    value="",
                    key=f"comment-{signal['signal_id']}",
                    height=80,
                )
                col_a, col_b, col_c = st.columns(3)
                if col_a.button(
                    ":white_check_mark: Approve",
                    key=f"appr-{signal['signal_id']}",
                ):
                    _resolve(signal["signal_id"], "approve", operator, comment)
                if col_b.button(
                    ":x: Reject", key=f"rej-{signal['signal_id']}"
                ):
                    _resolve(signal["signal_id"], "reject", operator, comment)
                if col_c.button(
                    ":mag: Request info",
                    key=f"info-{signal['signal_id']}",
                ):
                    _resolve(
                        signal["signal_id"], "request_info", operator, comment
                    )


def _resolve(
    signal_id: str,
    action: str,
    operator: str,
    comment: str,
) -> None:
    if not operator.strip():
        st.warning("Заполните Operator (your name)")
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
        st.success(f"Resolved {signal_id} as {action}")
        st.session_state["operator_name"] = operator.strip()
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Resolve failed: {exc}")


render_pending_table()
