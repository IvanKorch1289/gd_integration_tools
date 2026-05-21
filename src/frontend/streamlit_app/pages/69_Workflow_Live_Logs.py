"""Workflow Live Logs — read-only tail ClickHouse ``audit_events`` (Sprint 7 Team T4).

Read-only трансляция audit-логов из ClickHouse (см.
:mod:`src.backend.services.audit.clickhouse_audit_service`) с автообновлением
каждые ~2 секунды через ``st.fragment(run_every=2)``.

Важно:
    * Страница НЕ инициирует и НЕ управляет workflow — это исключительная
      зона ответственности Team T2/T3 (S4) и
      :mod:`src.backend.services.workflows`.
    * Чтение идёт через backend-endpoint ``GET /api/v1/admin/audit/tail``
      (если он зарегистрирован) — фронт не обращается к ClickHouse
      напрямую (см. CLAUDE.md ограничения слоёв).
    * При выключенном ``feature_flags.audit_clickhouse_enabled`` UI
      выводит баннер о неактивном источнике.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="Workflow Live Logs", page_icon=":memo:", layout="wide")
st.header(":memo: Workflow Live Logs (read-only)")
st.caption(
    "Стрим audit-событий из ClickHouse (`audit_events` table). Обновление "
    "каждые ~2 секунды. Только чтение — workflow-engine не вызывается."
)

# ---------------------------------------------------------------------------
# Sidebar — фильтры
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Фильтры tail")
    workflow_filter = st.text_input(
        "workflow_id / route_name substring",
        value="",
        help="Фильтр по имени workflow или route. Пусто — все события.",
    )
    severity_filter = st.selectbox(
        "Severity", options=["all", "info", "warning", "error"], index=0
    )
    tail_size = st.number_input(
        "Tail size",
        min_value=10,
        max_value=500,
        value=100,
        step=10,
        help="Число последних событий для отображения.",
    )
    autorefresh = st.toggle("Auto refresh (~2s)", value=True)


def _fetch_audit_tail() -> list[dict]:
    """Запрашивает tail audit-событий через REST.

    Returns:
        Список словарей событий в обратном хронологическом порядке.
        Пустой список при ошибке или отсутствии endpoint.
    """
    client = get_api_client()
    params: dict[str, object] = {"limit": int(tail_size)}
    if workflow_filter:
        params["route"] = workflow_filter
    if severity_filter != "all":
        params["severity"] = severity_filter
    try:
        records = client._request(  # type: ignore[attr-defined]
            "GET", "/api/v1/admin/audit/tail", params=params
        )
        if isinstance(records, list):
            return records
    except Exception:  # noqa: BLE001
        # Fallback на legacy-endpoint /api/v1/admin/audit (Sprint 2)
        try:
            records = client._request(  # type: ignore[attr-defined]
                "GET", "/api/v1/admin/audit", params=params
            )
            if isinstance(records, list):
                return records
        except Exception:  # noqa: BLE001
            return []
    return []


@st.fragment(run_every=2 if True else None)  # noqa: PLR2004
def _render_tail() -> None:
    """Рендерит ``tail`` audit-событий внутри Streamlit-фрагмента.

    ``st.fragment(run_every=2)`` обновляет только этот блок, не
    перерисовывая всю страницу. Это требование Streamlit 1.36+.
    """
    records = _fetch_audit_tail()
    st.caption(f"Получено событий: {len(records)}")
    if not records:
        st.info(
            "Нет событий. Возможные причины: feature_flag "
            "`audit_clickhouse_enabled=False`, ClickHouse недоступен, "
            "либо tail пуст."
        )
        return
    st.dataframe(records, use_container_width=True, height=600, hide_index=True)


if autorefresh:
    _render_tail()
else:
    # Без автообновления — простой одноразовый рендер по нажатию.
    if st.button("Обновить tail", type="primary"):
        _render_tail()
    else:
        st.info("Auto refresh отключён. Нажмите «Обновить tail» для разовой загрузки.")
