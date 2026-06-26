"""Streamlit page: DSL Debugger + Replay UI.

Два режима:
1. Step-through debugging — выполнение pipeline с trace per процессор
2. Replay — повтор исторических запросов из audit stream
"""

from __future__ import annotations

import json

import streamlit as st

from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient
from src.frontend.streamlit_app.shared.components import setup_page, related_pages_footer

setup_page()
st.title("🐛 Отладчик DSL и воспроизведение")
st.caption("Три режима: пошаговый Debugger (trace per процессор), Аудит Replay, Route Trace")

mode = st.radio(
    "Режим", ["Пошаговый Debugger", "Аудит Replay", "Route Trace"], horizontal=True
)

if mode == "Пошаговый Debugger":
    st.markdown("""
    Выполняет DSL маршрут с детальной трассировкой.
    Каждый процессор показывает input/output/duration.
    """)

    try:
        from src.backend.services.dsl_portal import list_route_ids

        available_routes = list_route_ids()
    except Exception as exc:
        st.error(f"Маршруты недоступны: {exc}")
        available_routes = []

    route_id = (
        st.selectbox("ID маршрута", available_routes)
        if available_routes
        else st.text_input("ID маршрута", help="route_id существующего маршрута (например: orders.create)")
    )
    body_str = st.text_area("Тело запроса (JSON)", value="{}", height=120)

    if st.button("▶️ Выполнить с трассировкой"):
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError as exc:
            st.error(f"Некорректный JSON: {exc}")
        else:
            try:
                result = DSLRoutesClient().execute_registered_route(route_id, body)

                col_result, col_trace = st.columns([1, 1])
                with col_result:
                    st.subheader("Результат")
                    st.json(
                        {
                            "status": result["status"],
                            "body": result["body"],
                            "error": result["error"],
                        }
                    )
                with col_trace:
                    st.subheader("Трассировка")
                    trace = result["trace"]
                    if trace:
                        for idx, entry in enumerate(trace):
                            with st.expander(
                                f"{idx + 1}. {entry.get('processor', 'unknown')} — {entry.get('duration_ms', 0):.1f}мс"
                            ):
                                st.json(entry)
                    else:
                        st.info("Нет данных трассировки")
            except Exception as exc:
                st.error(f"Ошибка выполнения: {exc}")

elif mode == "Аудит Replay":
    st.markdown("""
    Показывает историю HTTP запросов из Redis audit stream.
    Клик по записи — детальный просмотр + replay.
    """)

    limit = st.slider("Записей", 10, 500, 50)
    if st.button("🔄 Обновить"):
        try:
            from src.backend.services.dsl_portal import list_audit_records

            records = list_audit_records(count=limit)
            if not records:
                st.info("Нет записей аудита")
            else:
                for rec in records:
                    with st.expander(
                        f"{rec.get('method', '?')} {rec.get('path', '?')} — "
                        f"{rec.get('status_code', '?')} [{rec.get('duration_ms', 0):.1f}мс]"
                    ):
                        st.json(rec)
                        if st.button(
                            "🔁 Повторить", key=f"replay_{rec.get('timestamp', '')}"
                        ):
                            st.info(
                                "Функциональность replay: отправка сохранённого запроса по тому же пути"
                            )
        except Exception as exc:
            st.error(f"Audit stream недоступен: {exc}")

else:  # Route Trace
    st.markdown("Live-исполнения маршрутов через DSL tracer.")
    try:
        from src.backend.services.dsl_portal import list_recent_trace_events

        events = list_recent_trace_events(limit=100)
        if events:
            for ev in events:
                st.json(ev)
        else:
            st.info("Нет недавних событий")
    except Exception as exc:
        st.warning(f"Tracer недоступен: {exc}")

related_pages_footer("34_DSL_Отладчик")
