"""Sprint 13 K5 W3 — Pipeline Parallelism Analysis (PERF-6.8).

Визуализация DAG-параллелизма с подсветкой:

* Critical path (red);
* Parallelizable groups (same color box);
* Suggested optimizations (rule LR-PAR-001 / LR-PAR-002).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Параллелизм конвейера", "🔀")
st.title("🔀 Анализ параллелизма конвейера")
st.caption("DAG analyzer для DSL-маршрутов.")

client = get_api_client()


tab_route, tab_topn = st.tabs(["🎯 Анализ маршрута", "📊 Top-N по ускорению"])


with tab_route:
    st.subheader("Отчёт о параллелизме маршрута")
    try:
        routes = client.get("/api/v1/routes")
        names = [r.get("route_id", "") for r in routes.get("routes", []) if r]
    except Exception:  # noqa: BLE001
        names = []

    selected = (
        st.selectbox("Выбрать маршрут", options=names)
        if names
        else st.text_input("Имя маршрута")
    )

    if selected and st.button("Запустить анализ", type="primary"):
        try:
            report = client.get(f"/api/v1/admin/routes/{selected}/parallelism-report")
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown("### Группы DAG")
                for level_idx, group in enumerate(report.get("parallel_groups", [])):
                    box = "🔵" if len(group) > 1 else "⚪"
                    st.markdown(f"**Уровень {level_idx}** {box} — {', '.join(group)}")
                st.markdown("### Зависимости")
                for d in report.get("dependencies", []):
                    st.text(f"  {d['from']} ───[{d['via']}]──→ {d['to']}")

            with col2:
                st.metric("Всего шагов", report.get("total_steps", 0))
                st.metric(
                    "Ожидаемое ускорение", f"{report.get('estimated_speedup', 1.0):.2f}x"
                )
                hints = report.get("suggested_optimizations", [])
                if hints:
                    st.markdown("### Предложения")
                    for h in hints:
                        icon = "💡" if h["severity"] == "info" else "⚠️"
                        st.info(f"{icon} **{h['rule']}**: {h['message']}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Анализ не удался: {exc}")


with tab_topn:
    st.subheader("Top-N маршрутов по потенциалу ускорения")
    st.info(
        "Эта секция вызовет анализ для всех известных routes и "
        "отсортирует по estimated_speedup (highest impact first)."
    )
    n = st.slider("Top-N", 5, 50, 10)
    if st.button("Вычислить"):
        try:
            routes = client.get("/api/v1/routes")
            names = [r.get("route_id", "") for r in routes.get("routes", []) if r]
            results = []
            for rid in names[: n * 3]:  # Анализируем больше чем top-N
                try:
                    rep = client.get(f"/api/v1/admin/routes/{rid}/parallelism-report")
                    results.append((rid, rep.get("estimated_speedup", 1.0)))
                except Exception:  # noqa: BLE001, S112
                    continue
            results.sort(key=lambda x: x[1], reverse=True)
            for rid, speedup in results[:n]:
                st.markdown(f"- **{rid}** — `{speedup:.2f}x` speedup")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Top-N не удался: {exc}")
