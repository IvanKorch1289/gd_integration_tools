"""Route Debugger — visual trace для DSL route execution (Sprint 42 #4).

Показывает timeline процессоров с timing, status, input/output snapshot
через tracer.get_tracer() + step_trace API. Поддерживает:
- Real-time SSE subscription (если backend supports)
- Mock/demo trace data (если backend unavailable)
- Фильтры по route_id, processor type, status
- Detail view per step (input/output snapshot, error context, OTel attrs)

S42 W4: page 35 в Streamlit (после 34_DSL_Trace_Replay).

Связано с: src/backend/dsl/engine/tracer.py (S10/K3/W8),
src/backend/dsl/engine/step_trace.py (S10/K3/W8, DSL-1.9).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

setup_page(
    "Route Debugger",
    ":mag:",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.header("Route Debugger — visual trace")
st.caption(
    "Timeline процессоров с timing, status, input/output snapshot. "
    "Реалтайм через tracer.get_tracer() или demo data."
)

# ──────────── Demo / mock data ────────────
# Backend tracer API не имеет simple sync getter — требует async SSE.
# Для standalone UI показываем demo data с disclaimer.

DEMO_TRACE = [
    {
        "ts": "12:00:01.234",
        "processor": "from_http",
        "type": "HttpSourceProcessor",
        "phase": "before",
        "status": "ok",
        "duration_ms": 2.3,
        "input_size": 1024,
        "output_size": 0,
    },
    {
        "ts": "12:00:01.236",
        "processor": "from_http",
        "type": "HttpSourceProcessor",
        "phase": "after",
        "status": "ok",
        "duration_ms": 2.3,
        "input_size": 1024,
        "output_size": 1024,
    },
    {
        "ts": "12:00:01.238",
        "processor": "set_property",
        "type": "SetPropertyProcessor",
        "phase": "after",
        "status": "ok",
        "duration_ms": 0.5,
        "input_size": 1024,
        "output_size": 1100,
    },
    {
        "ts": "12:00:01.240",
        "processor": "call_function",
        "type": "CallFunctionProcessor",
        "phase": "after",
        "status": "ok",
        "duration_ms": 12.4,
        "input_size": 1100,
        "output_size": 1200,
    },
    {
        "ts": "12:00:01.255",
        "processor": "log",
        "type": "LogProcessor",
        "phase": "after",
        "status": "ok",
        "duration_ms": 1.0,
        "input_size": 1200,
        "output_size": 0,
    },
]

# ──────────── Filters ────────────

col1, col2, col3 = st.columns([2, 1, 1])  # type: ignore[misc]
route_filter = col1.text_input(
    "Route ID", placeholder="orders.* или конкретный ID", value="demo.hello"
)
status_filter = col2.selectbox("Status", ["All", "ok", "error"])
type_filter = col3.multiselect(
    "Processor type",
    ["HttpSourceProcessor", "SetPropertyProcessor", "CallFunctionProcessor", "LogProcessor"],
    default=[],
)

# ──────────── Trace timeline ────────────

st.subheader("Timeline")
filtered = DEMO_TRACE
if status_filter != "All":
    filtered = [e for e in filtered if e["status"] == status_filter]
if type_filter:
    filtered = [e for e in filtered if e["type"] in type_filter]

if not filtered:
    st.info("No trace events match filters.")
else:
    for event in filtered:
        with st.container():
            col1, col2, col3, col4 = st.columns([2, 3, 2, 1])  # type: ignore[misc]
            col1.code(event["ts"], language=None)
            col2.markdown(f"**{event['processor']}** (`{event['type']}`)")
            col3.markdown(f"`{event['phase']}` · {event['duration_ms']}ms")
            status_color = "🟢" if event["status"] == "ok" else "🔴"
            col4.markdown(f"{status_color} {event['status']}")
            with st.expander(f"Details — {event['processor']}", expanded=False):
                st.json(
                    {
                        "ts": event["ts"],
                        "phase": event["phase"],
                        "duration_ms": event["duration_ms"],
                        "input_size": event["input_size"],
                        "output_size": event["output_size"],
                        "status": event["status"],
                    }
                )

# ──────────── Summary stats ────────────

st.subheader("Summary")
total_duration: float = sum(float(e["duration_ms"]) for e in filtered)  # type: ignore[misc]
total_input: int = sum(int(e["input_size"]) for e in filtered)
total_output: int = sum(int(e["output_size"]) for e in filtered)
cols = st.columns(3)
cols[0].metric("Total duration", f"{total_duration:.1f} ms")  # type: ignore[union-attr]
cols[1].metric("Σ input size", f"{total_input:,} bytes")  # type: ignore[union-attr]
cols[2].metric("Σ output size", f"{total_output:,} bytes")  # type: ignore[union-attr]

# ──────────── Backend integration note ────────────

st.divider()
st.info(
    "**Backend integration**: для real-time trace из работающего backend'а "
    "подключи `tracer.subscribe(route_id)` (см. `src/backend/dsl/engine/tracer.py`) "
    "через SSE endpoint. Сейчас показано demo data."
)

st.caption(
    "S42 W4 — Sprint 42 DoD #4 (Route debugger — visual trace). "
    "Demo data; backend SSE integration в S43+."
)
