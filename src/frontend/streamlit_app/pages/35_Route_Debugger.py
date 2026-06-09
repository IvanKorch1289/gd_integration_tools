"""Route Debugger — visual trace для DSL route execution (Sprint 42 #4 + S44 W1).

Показывает timeline процессоров с timing, status, input/output snapshot
через ``GET /api/v1/admin/dsl-routes/{route_id}/traces`` (S44 W1).

S44 W1 backend integration:
- ``src/backend/dsl/engine/tracer.py::ExecutionTracer.get_recent_traces()``
  возвращает последние N end/error events из in-memory ring buffer
  (maxlen=1000 per route).
- Endpoint ``GET /admin/dsl-routes/{route_id}/traces?limit=N`` exposed via
  ``DSLRoutesClient.get_dsl_route_traces()``.
- Frontend fetches через ``api_clients.get_api_client().get_dsl_route_traces()``.

Fallback: если backend unavailable → demo data (S42 W4 baseline).

Refs:
- ``src/backend/dsl/engine/tracer.py`` (S10/K3/W8, extended S44 W1)
- ``src/backend/dsl/engine/step_trace.py`` (S10/K3/W8, DSL-1.9)
- ``src/backend/entrypoints/api/v1/endpoints/dsl_routes.py`` (ActionSpec
  ``get_dsl_route_traces``, S44 W1)
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client  # noqa: TID252
from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient
from src.frontend.streamlit_app.shared.components import setup_page

setup_page(
    "Route Debugger",
    ":mag:",
    layout="wide",
    initial_sidebar_state="expanded",
)
# Sprint 44 W1: используем DSLRoutesClient напрямую — APIClient generic
# wrapper не expose get_dsl_route_traces (lazy domain dispatch).
client = DSLRoutesClient()  # type: ignore[abstract]
_ = get_api_client()  # warm-up singleton init (back-compat)
st.header("Route Debugger — visual trace")
st.caption(
    "Timeline процессоров с timing, status, input/output snapshot. "
    "S44 W1: real data через /api/v1/admin/dsl-routes/{id}/traces. "
    "Fallback на demo data если backend unavailable."
)

# ──────────── Demo / fallback data ────────────

DEMO_TRACE: list[dict[str, Any]] = [
    {
        "timestamp": "12:00:01.234",
        "processor_name": "from_http",
        "processor_type": "HttpSourceProcessor",
        "phase": "end",
        "duration_ms": 2.3,
        "error": None,
    },
    {
        "timestamp": "12:00:01.238",
        "processor_name": "set_property",
        "processor_type": "SetPropertyProcessor",
        "phase": "end",
        "duration_ms": 0.5,
        "error": None,
    },
    {
        "timestamp": "12:00:01.240",
        "processor_name": "call_function",
        "processor_type": "CallFunctionProcessor",
        "phase": "end",
        "duration_ms": 12.4,
        "error": None,
    },
    {
        "timestamp": "12:00:01.255",
        "processor_name": "log",
        "processor_type": "LogProcessor",
        "phase": "end",
        "duration_ms": 1.0,
        "error": None,
    },
]


def _fetch_traces(route_id: str, limit: int = 100) -> tuple[list[dict[str, Any]], str]:
    """Fetch traces from backend. Returns (events, source).

    source ∈ {"backend", "demo"}. Backend может вернуть [] если
    маршрут ещё не выполнялся — это не fallback case.
    """
    try:
        events = client.get_dsl_route_traces(route_id, limit=limit)
        if events:
            return events, "backend"
        # Backend returned empty list — это легитимный ответ.
        return [], "backend"
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Backend unavailable ({exc!r}), показано demo data.")
        return DEMO_TRACE, "demo"


# ──────────── Filters ────────────

col1, col2, col3 = st.columns([2, 1, 1])  # type: ignore[misc]
route_filter = col1.text_input(
    "Route ID", placeholder="orders.* или конкретный ID", value="demo.hello"
)
limit_input = col2.number_input(
    "Limit", min_value=10, max_value=1000, value=100, step=10
)
reload = col3.button("Reload", type="primary")

# ──────────── Fetch + render ────────────

events, source = _fetch_traces(route_filter, limit=int(limit_input))
if source == "backend" and not events:
    st.info(
        f"Маршрут {route_filter!r} ещё не выполнялся или buffer очищен "
        "(post-restart). Persistent storage = TD-026 (S45+ D)."
    )

# Normalize: backend returns TraceEvent.to_dict() (route_id, processor_name,
# processor_type, phase, duration_ms, timestamp, error); demo data uses
# the same keys — единый pipeline.
filtered = list(events)
if source == "demo":
    st.caption(":test_tube: Demo data — backend trace buffer пуст.")

st.subheader(f"Timeline ({len(filtered)} events)")
if not filtered:
    st.info("No trace events to display.")
else:
    for event in filtered:
        proc = event.get("processor_name", "?")
        ptype = event.get("processor_type", "?")
        ts = event.get("timestamp", "?")
        phase = event.get("phase", "?")
        duration = event.get("duration_ms", 0.0)
        err = event.get("error")
        status = "error" if err else "ok"
        with st.container():
            c1, c2, c3, c4 = st.columns([2, 3, 2, 1])  # type: ignore[misc]
            c1.code(str(ts), language=None)
            c2.markdown(f"**{proc}** (`{ptype}`)")
            c3.markdown(f"`{phase}` · {duration} ms")
            color = "🟢" if status == "ok" else "🔴"
            c4.markdown(f"{color} {status}")
            with st.expander(f"Details — {proc}", expanded=False):
                payload: dict[str, Any] = {
                    "ts": ts,
                    "phase": phase,
                    "duration_ms": duration,
                    "status": status,
                }
                if err:
                    payload["error"] = err
                st.json(payload)

# ──────────── Summary stats ────────────

st.subheader("Summary")
if filtered:
    total_duration: float = sum(
        float(e.get("duration_ms") or 0.0) for e in filtered  # type: ignore[misc]
    )
    error_count: int = sum(1 for e in filtered if e.get("error"))
    cols = st.columns(3)
    cols[0].metric("Total events", str(len(filtered)))  # type: ignore[union-attr]
    cols[1].metric("Σ duration", f"{total_duration:.1f} ms")  # type: ignore[union-attr]
    cols[2].metric("Errors", str(error_count))  # type: ignore[union-attr]
else:
    st.caption("No events to summarize.")

st.caption(
    "S42 W4 baseline + S44 W1 backend wiring. "
    "Persistent trace storage = TD-026 (S45+ D)."
)
