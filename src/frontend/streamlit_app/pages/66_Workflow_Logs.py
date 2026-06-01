"""Streamlit-страница для просмотра workflow step-логов из ClickHouse.

Назначение:
    Visual viewer для workflow_step_log таблицы ClickHouse — фильтрация
    по workflow/tenant/date/status, табличный вывод, waterfall-диаграмма
    распределения duration по step_name, drill-down по конкретному
    workflow_id.

Контракт:
    * GET /api/v1/admin/workflow/step-logs (К3 Sprint 5 Wave 11) —
      листинг с фильтрами;
    * GET /api/v1/admin/workflow/step-logs/{workflow_id} — drill-down.

Поведение при отсутствии backend:
    Если К3 W11 endpoint ещё НЕ зарегистрирован, ``APIClient.list_step_logs``
    возвращает stub-данные (с пометкой ``__stub__=True``). Страница рисует
    предупреждение «K3 W11 endpoint не готов».

Feature flag:
    ``feature_flag.frontend_workflow_logs_page`` (default-OFF). При False —
    страница показывает баннер и завершает рендер через ``st.stop()``.

Sprint 5 K5 W1 — Frontend.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from src.backend.core.config.features import feature_flags  # noqa: E402
from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="Workflow Logs", page_icon=":memo:", layout="wide")

if not feature_flags.frontend_workflow_logs_page:
    st.warning(
        ":warning: Страница отключена "
        "(feature_flag.frontend_workflow_logs_page = False)"
    )
    st.stop()

st.title(":clipboard: Workflow Step Logs")
st.caption(
    "Визуализация записей workflow_step_log (ClickHouse) — фильтр по "
    "workflow/tenant/date/status, waterfall по длительностям, drill-down."
)

# ---------------------------------------------------------------------------
# Sidebar — фильтры
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Фильтры")
    workflow_name = st.text_input(
        "Workflow name",
        placeholder="credit_assessment",
        help="Substring match по имени workflow.",
    )
    tenant_id = st.text_input(
        "Tenant ID", placeholder="all tenants", help="Если пусто — все tenant'ы."
    )
    date_from = st.date_input(
        "Date from", value=datetime.utcnow().date() - timedelta(days=1)
    )
    date_to = st.date_input("Date to", value=datetime.utcnow().date())
    status_filter = st.multiselect(
        "Status", options=["ok", "fail", "retry", "timeout"], default=["ok", "fail"]
    )
    limit = st.number_input("Limit", min_value=10, max_value=1000, value=100, step=10)

# ---------------------------------------------------------------------------
# Main view — fetch + 3 tabs
# ---------------------------------------------------------------------------
api = get_api_client()

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
    st.stop()

df = pd.DataFrame(rows)

tab_table, tab_chart, tab_detail = st.tabs(
    [":bar_chart: Таблица", ":chart_with_upwards_trend: Waterfall", ":mag: Drill-down"]
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
        df[columns] if columns else df, use_container_width=True, hide_index=True
    )
    st.caption(f"Всего записей: {len(df)}")

with tab_chart:
    if "duration_ms" in df.columns and "step_name" in df.columns and not df.empty:
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
            "Workflow ID",
            options=ids,
            help="Выберите workflow для подробного просмотра steps.",
        )
        if selected_workflow:
            with st.spinner(f"Загрузка деталей {selected_workflow}..."):
                detail = api.get_step_detail(selected_workflow)
            if detail.get("__stub__"):
                st.info(":information_source: Drill-down — stub-данные.")
            st.json(detail)
