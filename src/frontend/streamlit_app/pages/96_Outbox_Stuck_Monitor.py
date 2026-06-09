"""Outbox Stuck-Pending Monitor — Sprint 75 W1 (observability).

Live dashboard для outbox_stuck_pending_count Prometheus gauge.
Показывает:
  * Текущее значение stuck-pending count (last sample)
  * Trend за 24h (если Prometheus доступен)
  * Threshold configuration
  * Alert rules summary (S73 W1)
  * Runbook quick reference

Использует:
  * Prometheus query через httpx (если PROMETHEUS_URL задан)
  * Иначе — in-memory read из gauge state (если доступен)

Use:
  streamlit run src/frontend/streamlit_app/app.py
  → Navigate to "Outbox Stuck Monitor" в sidebar.
"""

# ruff: noqa: I001

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Outbox Stuck Monitor", "⏱")

st.title("⏱ Outbox Stuck-Pending Monitor")
st.caption(
    "Sprint 75 W1 — Live dashboard для outbox_stuck_pending_count gauge "
    "(S72 W2 → S73 W1 → S75 W1 chain)"
)

# Configuration section
st.subheader("⚙️ Configuration")

col1, col2 = st.columns(2)
with col1:
    threshold = st.number_input(
        "Threshold (seconds)",
        min_value=60,
        max_value=3600,
        value=int(os.getenv("STUCK_MONITOR_THRESHOLD_SECONDS", "300")),
        step=60,
        help="Pending messages старше этого threshold считаются 'stuck'.",
    )
with col2:
    sample_interval = st.number_input(
        "Sample interval (seconds)",
        min_value=10,
        max_value=600,
        value=int(os.getenv("STUCK_MONITOR_SAMPLE_INTERVAL_SECONDS", "60")),
        step=10,
        help="Как часто stuck-monitor обновляет Prometheus gauge.",
    )

st.caption(
    f"Current config: threshold = {threshold}s ({threshold // 60} min), "
    f"sample = {sample_interval}s"
)

# Live status section
st.subheader("📊 Live Status")

prometheus_url = os.getenv("PROMETHEUS_URL", "")

if prometheus_url:
    st.caption(f"Querying Prometheus at `{prometheus_url}`")
    try:
        import httpx

        query_url = f"{prometheus_url}/api/v1/query"
        response = httpx.get(
            query_url,
            params={"query": "outbox_stuck_pending_count"},
            timeout=5.0,
        )
        if response.status_code == 200:
            data = response.json()
            results = data.get("data", {}).get("result", [])
            if results:
                value = float(results[0]["value"][1])
                st.metric(
                    label="Stuck-pending count (current)",
                    value=int(value),
                    delta=None,
                    delta_color="inverse" if value > 0 else "off",
                )
                if value > 0:
                    st.warning(
                        f"⚠️ {int(value)} messages stuck older than {threshold}s. "
                        f"Check runbook below."
                    )
                else:
                    st.success("✅ No stuck messages. Worker healthy.")
            else:
                st.info("No data points yet. Wait for first sample (60s).")
        else:
            st.error(f"Prometheus query failed: HTTP {response.status_code}")
    except Exception as exc:
        st.error(f"Prometheus query error: {exc}")
else:
    st.info(
        "Set `PROMETHEUS_URL` env var для live queries. "
        "Showing in-memory state (best-effort, same-process only)."
    )
    # In-memory fallback: try to read from default_stuck_monitor.
    # Только работает если streamlit запущен в ТОМ ЖЕ process что и stuck_monitor.
    # Production deploy: используйте PROMETHEUS_URL или см. CLI helper ниже.
    in_memory_available = False
    try:
        from src.backend.infrastructure.messaging.outbox import stuck_monitor

        monitor = stuck_monitor.default_stuck_monitor
        in_memory_available = True
        st.metric(
            label="Stuck-pending count (in-memory)",
            value=monitor.last_count if monitor.last_count >= 0 else "—",
            delta=f"{monitor.samples_total} samples taken",
        )
    except ImportError:
        st.warning(
            "⚠️ StuckStuckMonitor module not importable в этом process. "
            "Streamlit app запущен в отдельном worker — нужен PROMETHEUS_URL."
        )
    except Exception as exc:
        st.error(f"In-memory read error: {exc}")

# CLI helper reference (для ops)
with st.expander("🔧 CLI helpers (без UI)"):
    st.markdown(
        """
Для production мониторинга без Streamlit/Prometheus:

```bash
# Read stuck-monitor state from JSON file (если monitor
# пишет в /tmp/stuck_monitor_state.json)
cat /tmp/stuck_monitor_state.json | jq .

# Direct database query (manual fallback)
psql -h <host> -U <user> -d <db> -c "
  SELECT COUNT(*) AS stuck_count
  FROM outbox_messages
  WHERE status = 'pending'
    AND created_at < now() - interval '5 minutes'
    AND retry_count = 0;
"

# Restart stuck-monitor если он dead
systemctl restart gd-integration-tools
```
"""
    )

# Alert rules summary
st.subheader("🚨 Alert Rules (S73 W1)")

alert_rules: list[dict[str, Any]] = [
    {
        "name": "OutboxStuckPendingHigh",
        "severity": "warning",
        "condition": "count > 0 для 5 min",
        "action": "Slack #platform-alerts",
    },
    {
        "name": "OutboxStuckPendingCritical",
        "severity": "critical (P0)",
        "condition": "count > 100 для 15 min",
        "action": "PagerDuty + Slack #incidents",
    },
]

st.dataframe(alert_rules, use_container_width=True, hide_index=True)

# Runbook
st.subheader("📋 Runbook")

st.markdown(
    """
При `OutboxStuckPendingHigh`:

1. **Проверить worker state**:
   ```bash
   curl -s http://localhost:8000/admin/outbox/status | jq .worker_state
   ```
2. **Если worker dead** — auto-recovery через FastAPI lifespan, либо restart:
   ```bash
   systemctl restart gd-integration-tools
   ```
3. **Если worker alive но stuck** — DB lock contention:
   ```sql
   SELECT * FROM pg_locks WHERE relation = 'outbox_messages'::regclass;
   ```
4. **Manual replay** (восстановить из БД):
   ```bash
   make outbox-replay-stuck
   ```

См. также: [Outbox / DLQ depth dashboard](/d/gd-outbox-dlq-depth) для cross-reference.
"""
)

# Footer
st.divider()
st.caption(
    "S75 W1 — Streamlit page для S72 W2 (gauge) + S73 W1 (alerts). "
    "Chain: count_stuck_pending() → Prometheus gauge → Grafana alerts → this page."
)
