"""Streamlit-страница для просмотра workflow step-логов + live audit tail.

Вкладки:
* Step Logs — ClickHouse workflow_step_log.
* Live Audit Tail — read-only tail audit_events.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc

import pandas as pd
import streamlit as st

from src.backend.core.config.features import feature_flags  # noqa: E402
from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page()
if not feature_flags.frontend_workflow_logs_page:
    st.warning(
        ":warning: Страница отключена "
        "(feature_flag.frontend_workflow_logs_page = False)"
    )
    st.stop()

st.title(":clipboard: Логи Workflow")
st.caption(
    "Визуализация записей workflow_step_log (ClickHouse) — фильтр по "
    "workflow/tenant/date/status, waterfall по длительностям, drill-down. "
    "Live audit tail — автообновление каждые ~2 сек."
)

api = get_api_client()

tab_step, tab_live = st.tabs(["Step Logs", "Live-хвост аудита"])

with tab_step:
    st.subheader("Фильтры Step Logs")
    workflow_name = st.text_input(
        "Имя workflow",
        placeholder="credit_assessment",
        help="Substring match по имени workflow.",
        key="step_workflow",
    )
    tenant_id = st.text_input(
        "ID тенанта",
        placeholder="all tenants",
        help="Если пусто — все tenant'ы.",
        key="step_tenant",
    )
    date_from = st.date_input(
        "Дата с", value=datetime.now(UTC).date() - timedelta(days=1), key="step_from"
    )
    date_to = st.date_input("Дата по", value=datetime.now(UTC).date(), key="step_to")
    status_filter = st.multiselect(
        "Статус",
        options=["ok", "fail", "retry", "timeout"],
        default=["ok", "fail"],
        key="step_status",
    )
    limit = st.number_input(
        "Лимит", min_value=10, max_value=1000, value=100, step=10, key="step_limit"
    )

    with st.spinner("Загрузка step-логов..."):
        rows = api.list_step_logs(
            workflow_name=workflow_name or None,
            tenant_id=tenant_id or None,
            date_from=str(date_from),
            date_to=str(date_to),
            status=status_filter or None,
            limit=int(limit),
        )

    if rows and any(r.get("__stub__") for r in rows):
        st.info(
            ":information_source: К3 W11 endpoint /api/v1/admin/workflow/step-logs "
            "ещё не зарегистрирован — показываются stub-данные."
        )

    if not rows:
        st.info("Нет данных по выбранным фильтрам.")
    else:
        df = pd.DataFrame(rows)

        tab_table, tab_chart, tab_detail = st.tabs(
            [
                ":bar_chart: Таблица",
                ":chart_with_upwards_trend: Waterfall",
                ":mag: Drill-down",
            ]
        )

        with tab_table:
            columns = [
                c
                for c in (
                    "workflow_id",
                    "workflow_name",
                    "step_name",
                    "status",
                    "duration_ms",
                    "tenant_id",
                    "ts",
                )
                if c in df.columns
            ]
            st.dataframe(
                df[columns] if columns else df,
                width='stretch',
                hide_index=True,
            )
            st.caption(f"Всего записей: {len(df)}")

        with tab_chart:
            if (
                "duration_ms" in df.columns
                and "step_name" in df.columns
                and not df.empty
            ):
                chart_df = (
                    df.groupby("step_name")["duration_ms"]
                    .sum()
                    .sort_values(ascending=False)
                    .head(20)
                )
                st.subheader("Top-20 step_name по суммарной длительности (ms)")
                st.bar_chart(chart_df)
            else:
                st.info("Нет колонок duration_ms / step_name для построения chart.")

        with tab_detail:
            if "workflow_id" in df.columns:
                ids = df["workflow_id"].dropna().astype(str).unique().tolist()
            else:
                ids = []

            if not ids:
                st.info("Нет workflow_id в текущей выборке для drill-down.")
            else:
                selected_workflow = st.selectbox(
                    "ID Воркфлоу",
                    options=ids,
                    help="Выберите workflow для подробного просмотра steps.",
                )
                if selected_workflow:
                    with st.spinner(f"Загрузка деталей {selected_workflow}..."):
                        detail = api.get_step_detail(selected_workflow)
                    if detail.get("__stub__"):
                        st.info(":information_source: Drill-down — stub-данные.")
                    st.json(detail)

with tab_live:
    st.header(":memo: Логи Workflow в реальном времени (только чтение)")
    st.caption(
        "Стрим audit-событий из ClickHouse (`audit_events` table). Обновление "
        "каждые ~2 секунды. Только чтение — workflow-engine не вызывается."
    )

    st.subheader("Фильтры tail")
    workflow_filter = st.text_input(
        "Подстрока workflow_id / route_name",
        value="",
        help="Фильтр по имени workflow или route. Пусто — все события.",
        key="live_workflow",
    )
    severity_filter = st.selectbox(
        "Уровень важности",
        options=["all", "info", "warning", "error"],
        index=0,
        key="live_severity",
    )
    tail_size = st.number_input(
        "Размер tail",
        min_value=10,
        max_value=500,
        value=100,
        step=10,
        help="Число последних событий для отображения.",
        key="live_size",
    )
    autorefresh = st.toggle("Авто-обновление (~2s)", value=True, key="live_refresh")

    def _fetch_audit_tail() -> list[dict]:
        params: dict[str, object] = {"limit": int(tail_size)}
        if workflow_filter:
            params["route"] = workflow_filter
        if severity_filter != "all":
            params["severity"] = severity_filter
        try:
            records = api._request("GET", "/api/v1/admin/audit/tail", params=params)
            if isinstance(records, list):
                return records
        except Exception:  # noqa: BLE001
            try:
                records = api._request("GET", "/api/v1/admin/audit", params=params)
                if isinstance(records, list):
                    return records
            except Exception:  # noqa: BLE001
                return []
        return []

    @st.fragment(run_every=2)
    def _render_tail() -> None:
        records = _fetch_audit_tail()
        st.caption(f"Получено событий: {len(records)}")
        if not records:
            st.info(
                "Нет событий. Возможные причины: feature_flag "
                "`audit_clickhouse_enabled=False`, ClickHouse недоступен, "
                "либо tail пуст."
            )
            return
        st.dataframe(records, width='stretch', height=600, hide_index=True)

    if autorefresh:
        _render_tail()
    else:
        if st.button("Обновить tail", type="primary"):
            _render_tail()
        else:
            st.info(
                "Auto refresh отключён. Нажмите «Обновить tail» для разовой загрузки."
            )
