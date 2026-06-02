"""Streamlit page AI Feedback (Sprint 11 K5 W2).

Просмотр labeled feedback + DSPy training runs.
Feature-flag: ``dspy_feedback_loop``.
"""

from __future__ import annotations

import streamlit as st

try:
    from src.frontend.streamlit_app.api_client import APIClient
except ImportError:  # pragma: no cover
    APIClient = None  

st.set_page_config(page_title="AI Feedback", page_icon="📝", layout="wide")
st.title("📝 AI Feedback & DSPy Training")
st.caption(
    "Просмотр labeled feedback и DSPy training runs. "
    "Активируется feature-flag `dspy_feedback_loop`."
)


def _client() -> "APIClient":
    if APIClient is None:
        st.error("APIClient недоступен.")
        st.stop()
    return APIClient()


def main() -> None:
    tab_runs, tab_counts = st.tabs(["Training Runs", "Labeled Counts"])

    with tab_runs:
        try:
            data = _client().get("/admin/feedback/training-runs?limit=10")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Ошибка: {exc}")
            data = {"runs": [], "count": 0}
        runs = data.get("runs", []) if isinstance(data, dict) else []
        if not runs:
            st.info(
                "Нет завершённых runs. Cron `ai_feedback_dspy_nightly` запускается в 03:00 при включённом feature-flag."
            )
        else:
            for r in runs:
                with st.expander(f"Run {r.get('id')} — {r.get('completed_at')}"):
                    st.json(r)

    with tab_counts:
        tenant = st.text_input("Tenant ID (опционально)")
        try:
            data = _client().get(
                f"/admin/feedback/labeled-count{('?tenant_id=' + tenant) if tenant else ''}"
            )
            count = data.get("count", 0) if isinstance(data, dict) else 0
            st.metric("Labeled feedback", count)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Ошибка: {exc}")


main()
