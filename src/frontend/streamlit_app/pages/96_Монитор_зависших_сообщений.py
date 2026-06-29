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

from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page()

st.title("⏱ Монитор зависших сообщений Outbox")
st.caption(
    "Live dashboard для outbox_stuck_pending_count "

    "gauge (Pending → Sent → Failed)."
)

# Configuration section
st.subheader("⚙️ Конфигурация")

col1, col2 = st.columns(2)
with col1:
    threshold = st.number_input(
        "Порог (секунды)",
        min_value=60,
        max_value=3600,
        value=int(os.getenv("STUCK_MONITOR_THRESHOLD_SECONDS", "300")),
        step=60,
        help="Pending messages старше этого threshold считаются 'stuck'.",
    )
with col2:
    sample_interval = st.number_input(
        "Интервал сэмпла (секунды)",
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
st.subheader("📊 Текущий статус")

prometheus_url = os.getenv("PROMETHEUS_URL", "")

if prometheus_url:
    st.caption(f"Querying Prometheus at `{prometheus_url}`")
    try:
        import httpx

        query_url = f"{prometheus_url}/api/v1/query"
        response = httpx.get(
            query_url, params={"query": "outbox_stuck_pending_count"}, timeout=5.0
        )
        if response.status_code == 200:
            data = response.json()
            results = data.get("data", {}).get("result", [])
            if results:
                value = float(results[0]["value"][1])
                st.metric(
                    label="Количество зависших (текущее)",
                    value=int(value),
                    delta=None,
                    delta_color="inverse" if value > 0 else "off",
                )
                if value > 0:
                    st.warning(
                        f"⚠️ {int(value)} messages stuck older than {threshold}s. "
                        f"См. runbook ниже."
                    )
                else:
                    st.success("✅ Нет застрявших сообщений. Worker работает штатно.")
            else:
                st.info("Нет точек данных. Подождите первого сэмпла (60 сек).")
        else:
            st.error(f"Prometheus query failed: HTTP {response.status_code}")
    except Exception as exc:
        st.error(f"Prometheus query error: {exc}")
else:
    st.info(
        "Set `PROMETHEUS_URL` env var для live queries. "
        "Показано состояние из памяти (best-effort, только в текущем процессе)."
    )
    # In-memory fallback: try to read from default_stuck_monitor.
    # Только работает если streamlit запущен в ТОМ ЖЕ process что и stuck_monitor.
    # Production deploy: используйте PROMETHEUS_URL или см. CLI helper ниже.
    in_memory_available = False
    try:
        # S6 fix: facade import via dsl_portal (R3.10d / S36).
        from src.backend.services.dsl_portal import get_default_stuck_monitor

        monitor = get_default_stuck_monitor()
        in_memory_available = True
        st.metric(
            label="Количество зависших (в памяти)",
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

# Per-transport breakdown (S81 W4, ND-001 step 9)
st.subheader("📊 Per-Transport Breakdown")

if prometheus_url:
    # Query per-transport gauges (S81 W2: label-based)
    per_transport_query = 'outbox_stuck_pending_count{transport!="_aggregate_"}'
    try:
        with st.spinner("Запрос per-transport метрик к Prometheus..."):
            response = httpx.get(
                f"{prometheus_url}/api/v1/query",
                params={"query": per_transport_query},
                timeout=5.0,
            )
        if response.status_code == 200:
            data = response.json()
            results = data.get("data", {}).get("result", [])
            if results:
                transport_data: list[dict[str, Any]] = []
                for r in results:
                    metric = r.get("metric", {})
                    value = r.get("value", [None, "0"])[1]
                    transport_data.append(
                        {
                            "transport": metric.get("transport", "unknown"),
                            "stuck_count": int(float(value)),
                        }
                    )
                # Sort descending по count
                transport_data.sort(key=lambda x: x["stuck_count"], reverse=True)
                st.dataframe(transport_data, width='stretch', hide_index=True)
                # Top transport highlight
                if transport_data:
                    top = transport_data[0]
                    if top["stuck_count"] > 0:
                        st.warning(
                            f"⚠️ Top transport: **{top['transport']}** "
                            f"с **{top['stuck_count']}** stuck messages. "
                            f"См. Grafana panel #5 (per-transport breakdown)."
                        )
            else:
                st.success("✅ No stuck messages ни в одном transport.")
    except Exception as exc:
        st.error(f"Per-transport query failed: {exc}")
else:
    st.info(
        "Set `PROMETHEUS_URL` для per-transport breakdown. "
        "В-memory fallback показывает только aggregate."
    )

# Alert rules summary
st.subheader("🚨 Alert Rules")

alert_rules: list[dict[str, Any]] = [
    {
        "name": "OutboxStuckPendingHigh",
        "severity": "warning",
        "condition": "aggregate > 0 для 5 min",
        "action": "Slack #platform-alerts  # канал оповещений",
    },
    {
        "name": "OutboxStuckPendingCritical",
        "severity": "critical (P0)",
        "condition": "aggregate > 100 для 15 min",
        "action": "PagerDuty + Slack #incidents",
    },
    {
        "name": "OutboxStuckPendingByTransportHigh",
        "severity": "warning",
        "condition": "max(per-transport) > 50 для 10 min",
        "action": "Slack #platform-alerts (with transport label)",
    },
]

st.dataframe(alert_rules, width='stretch', hide_index=True)

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
    "S75 W1 + S80 W2 + S81 W4 — Streamlit page для S72 W2 (gauge) + "
    "S73 W1 (alerts) + S81 W2 (per-transport label) + S81 W4 (per-transport section). "
    "Chain: count_stuck_pending() → Prometheus gauge (per-transport) → "
    "Grafana alerts (3 rules) → this page."
)

related_pages_footer("96_Монитор_зависших_сообщений")
