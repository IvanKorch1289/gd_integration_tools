"""DSL Usage Audit — мониторинг использования DSL процессоров (K3 S19 W6).

Собирает статистику использования DSL процессоров:
- top-N steps по частоте использования в маршрутах;
- avg latency per step type;
- error rate per step type.

Данные получаются через вызов audit-скрипта tools/audit/dsl_usage_audit.py
с флагом ``feature_flags.dsl_usage_audit_enabled = True``.
"""

# NOTE (S93 W2-C11): PYTHONPATH=$(pwd) устанавливается manage.py run-frontend.
# Прямой запуск `streamlit run` без PYTHONPATH упадёт с ImportError.

from __future__ import annotations

import sys

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page()
st.header(":bar_chart: Аудит использования DSL")
st.caption("Статистика использования DSL процессоров")

client = get_api_client()

# ── Controls
col1, col2, col3 = st.columns(3)
top_n = col1.number_input(
    "Top N процессоров", min_value=1, max_value=100, value=20, step=5
)
auto_refresh = col2.toggle("Авто-обновление (30s)", value=False)
show_details = col3.toggle("Показать детали", value=True)


# ── Run audit
def run_audit(top: int = 20) -> dict:
    """Вызывает dsl_usage_audit.py и возвращает результат."""
    import json
    import subprocess
    from pathlib import Path

    # S93 W2-C11: project_root from PYTHONPATH (manage.py run-frontend sets it).
    project_root = (
        Path.cwd()
        if Path.cwd().name == "gd_integration_tools"
        else Path(__file__).resolve().parents[4]
    )
    audit_script = project_root / "tools" / "audit" / "dsl_usage_audit.py"
    if not audit_script.exists():
        return {"error": f"Audit script not found: {audit_script}"}

    try:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(audit_script),
                "--top",
                str(top),
                "--output",
                "json",
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(project_root),
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {"error": result.stderr or f"Exit code: {result.returncode}"}
    except subprocess.TimeoutExpired:
        return {"error": "Аудит превысил таймаут (60 сек)"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Fetch data
if "audit_data" not in st.session_state or auto_refresh:
    with st.spinner("Собираем статистику использования DSL..."):
        st.session_state["audit_data"] = run_audit(top=top_n)

data = st.session_state.get("audit_data", {})

if "error" in data:
    st.error(f"Ошибка при запуске аудита: {data['error']}")
    st.stop()

total_processors = data.get("total_processors", 0)
top_processors = data.get("top_processors", [])

st.divider()

# ── Summary metrics
st.subheader("Сводка")
metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
metrics_col1.metric("Всего процессоров", total_processors)
metrics_col2.metric("Показано в топе", len(top_processors))
metrics_col3.metric("Top N", top_n)

st.divider()

# ── Main table
if top_processors:
    st.subheader(f"Топ-{len(top_processors)} процессоров по использованию")

    # Prepare dataframe
    import pandas as pd

    df = pd.DataFrame(top_processors)

    # Rename columns for display
    df_display = df.rename(
        columns={
            "processor_name": "Имя процессора",
            "processor_class": "Class",
            "usage_count": "Usage Count",
            "avg_latency_ms": "Средняя задержка (мс)",
            "error_rate_pct": "Доля ошибок (%)",
            "samples": "Samples",
        }
    )

    if show_details:
        st.dataframe(df_display, width='stretch', height=400)
    else:
        st.dataframe(
            df_display[
                [
                    "Имя процессора",
                    "Class",
                    "Usage Count",
                    "Средняя задержка (мс)",
                    "Доля ошибок (%)",
                ]
            ],
            width='stretch',
            height=400,
        )

    # ── Charts
    st.divider()
    st.subheader("Визуализация")

    chart_col1, chart_col2 = st.columns(2)

    # Usage bar chart
    with chart_col1:
        st.write("**Использование по процессорам**")
        if not df_display.empty:
            chart_data = df_display[["Имя процессора", "Usage Count"]].set_index(
                "Имя процессора"
            )
            st.bar_chart(chart_data, horizontal=True, height=400)

    # Latency bar chart
    with chart_col2:
        st.write("**Средняя латентность (ms)**")
        if not df_display.empty:
            latency_data = df_display[["Имя процессора", "Средняя задержка (мс)"]].set_index(
                "Имя процессора"
            )
            st.bar_chart(latency_data, horizontal=True, height=400)

    # Error rate chart
    if show_details and "Доля ошибок (%)" in df_display.columns:
        st.divider()
        st.write("**Доля ошибок (%)**")
        error_data = df_display[["Имя процессора", "Доля ошибок (%)"]].set_index(
            "Имя процессора"
        )
        st.bar_chart(error_data, horizontal=True, height=300)

else:
    st.info(
        "Нет данных о использовании процессоров. Проверьте, что DSL маршруты загружены."
    )

st.divider()

# ── Footer note
st.caption(
    "Note: Статистика собирается из кода процессоров и YAML-манифестов маршрутов. "
    "Latency и error rate отражают только доступные из SLO-трекера данные."
)

if not auto_refresh:
    st.caption("⏸ Авто-обновление отключено")


@st.fragment(run_every="30s")
def _render_audit_refresh() -> None:
    """Auto-refresh audit fragment (Streamlit 1.33+ run_every)."""
    if not auto_refresh:
        return

    st.caption("Авто-обновление через 30 секунд...")
    # Force re-execution by accessing session state trigger
    if "audit_data" in st.session_state:
        del st.session_state["audit_data"]
    st.rerun(scope="fragment")


_render_audit_refresh()

related_pages_footer("86_Аудит_использования_DSL")
