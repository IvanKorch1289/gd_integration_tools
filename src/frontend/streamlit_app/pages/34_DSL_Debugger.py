"""Streamlit page: DSL Debugger + Replay UI.

Два режима:
1. Step-through debugging — выполнение pipeline с trace per процессор
2. Replay — повтор исторических запросов из audit stream
"""

from __future__ import annotations

import asyncio
import json

import streamlit as st

st.set_page_config(page_title="DSL Debugger", page_icon="🐛", layout="wide")
st.title("🐛 DSL Debugger & Replay")

mode = st.radio(
    "Режим", ["Step-through Debugger", "Replay Audit", "Route Trace"], horizontal=True
)

if mode == "Step-through Debugger":
    st.markdown("""
    Выполняет DSL маршрут с детальной трассировкой.
    Каждый процессор показывает input/output/duration.
    """)

    try:
        from src.backend.dsl.registry import route_registry

        available_routes = list(route_registry._routes.keys())
    except Exception as exc:
        st.error(f"Routes unavailable: {exc}")
        available_routes = []

    route_id = (
        st.selectbox("Route ID", available_routes)
        if available_routes
        else st.text_input("Route ID")
    )
    body_str = st.text_area("Request body (JSON)", value="{}", height=120)

    if st.button("▶️ Execute with trace"):
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")
        else:
            try:
                from src.backend.dsl.engine.execution_engine import ExecutionEngine

                pipeline = route_registry.get(route_id)
                engine = ExecutionEngine()
                exchange = asyncio.run(engine.execute(pipeline, body=body))

                col_result, col_trace = st.columns([1, 1])
                with col_result:
                    st.subheader("Result")
                    st.json(
                        {
                            "status": exchange.status.value,
                            "body": exchange.out_message.body
                            if exchange.out_message
                            else exchange.in_message.body,
                            "error": exchange.error,
                        }
                    )
                with col_trace:
                    st.subheader("Trace")
                    trace = exchange.properties.get("_trace", [])
                    if trace:
                        for idx, entry in enumerate(trace):
                            with st.expander(
                                f"{idx + 1}. {entry.get('processor', 'unknown')} — {entry.get('duration_ms', 0):.1f}ms"
                            ):
                                st.json(entry)
                    else:
                        st.info("No trace data")
            except Exception as exc:
                st.error(f"Execution failed: {exc}")

elif mode == "Replay Audit":
    st.markdown("""
    Показывает историю HTTP запросов из Redis audit stream.
    Клик по записи — детальный просмотр + replay.
    """)

    limit = st.slider("Записей", 10, 500, 50)
    if st.button("🔄 Refresh"):
        try:
            from src.backend.entrypoints.middlewares.audit_replay import (
                list_audit_records,
            )

            records = asyncio.run(list_audit_records(count=limit))
            if not records:
                st.info("No audit records")
            else:
                for rec in records:
                    with st.expander(
                        f"{rec.get('method', '?')} {rec.get('path', '?')} — "
                        f"{rec.get('status_code', '?')} [{rec.get('duration_ms', 0):.1f}ms]"
                    ):
                        st.json(rec)
                        if st.button(
                            "🔁 Replay", key=f"replay_{rec.get('timestamp', '')}"
                        ):
                            st.info(
                                "Replay functionality: send stored request to same path"
                            )
        except Exception as exc:
            st.error(f"Audit stream unavailable: {exc}")

else:  # Route Trace
    st.markdown("Live route executions через DSL tracer.")
    try:
        from src.backend.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        events = (
            list(tracer._recent_events)[-100:]
            if hasattr(tracer, "_recent_events")
            else []
        )
        if events:
            for ev in events:
                st.json(ev)
        else:
            st.info("No recent events")
    except Exception as exc:
        st.warning(f"Tracer unavailable: {exc}")
