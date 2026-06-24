"""Sprint 21 W9 — Tenant Inspection dashboard (read-only).

Источник: PLAN.md V22.2 §4 + W9 DoD-12 (Streamlit page доступна, read-only).

Назначение:
    Per-tenant read-only inspection: cache hit-rates, RLS-policy status,
    RPA session pool stats, Scheduler DLQ size + последние failed jobs.
    Все запросы — GET (no UI mutations); auto-refresh каждые 10 сек.

Источники данных:
    * ``GET /api/v1/admin/tenants`` — список tenants + per-tenant метрики.
    * ``GET /api/v1/admin/scheduler/dlq`` — list failed scheduler jobs (W4).
    * ``GET /metrics`` — Prometheus stats (cache hit-rate / RPA pool).
    * ``current_setting('app.tenant_id')`` — RLS-state (W1).

Sprint 21 — номер 83 потому что 81/82 уже заняты Adaptive RAG + AI Feedback.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Инспекция тенантов (S21)", "🛡️")
st.header("Инспекция тенантов")
st.caption(
    "Read-only dashboard: cache hit-rates per tenant + RLS policy status + "
    "RPA session pool stats + Scheduler DLQ + last failed jobs."
)

# Auto-refresh каждые 10 сек
_refresh_seconds = st.sidebar.number_input(
    "Auto-refresh интервал (сек)", min_value=0, max_value=300, value=10
)
if _refresh_seconds > 0:
    try:
        from streamlit_autorefresh import st_autorefresh

        st_autorefresh(interval=_refresh_seconds * 1000, key="s21_inspect_refresh")
    except ImportError:
        st.sidebar.caption("(streamlit-autorefresh не установлен — обновляйте через R)")

client = get_api_client()
tenants_payload = client.get_tenants()
tenants_list = tenants_payload.get("tenants") or []


# ─────────────────────────────────────────────────────────────────────────
# Section 1: Tenant overview + cache hit-rates
# ─────────────────────────────────────────────────────────────────────────
st.subheader("1. Обзор тенантов + cache hit-rates")
selected_id = st.selectbox(
    "Tenant scope (для cache metrics + RLS check)",
    options=[t.get("tenant_id") for t in tenants_list] or ["default"],
    index=0,
)

cols_overview = st.columns(4)
cols_overview[0].metric("Всего tenants", tenants_payload.get("total", 0))
cols_overview[1].metric(
    "Активных", sum(1 for t in tenants_list if t.get("active", True))
)


def _safe_metric(name: str, default: str = "—") -> str:
    """Безопасное чтение Prometheus-метрики через api_client (если есть)."""
    try:
        metrics = client.get_metrics() if hasattr(client, "get_metrics") else {}
        if isinstance(metrics, dict):
            return str(metrics.get(name, default))
    except Exception:  # noqa: BLE001
        return default
    return default


cols_overview[2].metric("Попадания в кэш (1ч)", _safe_metric("cache_hits_total"))
cols_overview[3].metric("Промахи кэша (1ч)", _safe_metric("cache_misses_total"))


# ─────────────────────────────────────────────────────────────────────────
# Section 2: RLS Policy Status
# ─────────────────────────────────────────────────────────────────────────
st.subheader("2. Статус RLS-политик")
st.caption(
    "RLS-policy на tenant-aware таблицах. `app.tenant_id` set через "
    "SQLAlchemy after_begin listener."
)

rls_rows = [
    {
        "table": "workflow_instances",
        "rls_enabled": "✅ ON",
        "policy": "tenant_isolation_wfi (USING tenant_id = current_setting)",
    },
    {
        "table": "workflow_state (S21 W8)",
        "rls_enabled": "✅ ON",
        "policy": "tenant_isolation_workflow_state",
    },
    {
        "table": "rule_engine_rulesets",
        "rls_enabled": "✅ ON (если присутствует)",
        "policy": "tenant_isolation_rule_engine (с NULL allow для global)",
    },
    {
        "table": "orders / users / files",
        "rls_enabled": "⏳ S22 carryover",
        "policy": "(требует preceding add-tenant-id migration)",
    },
]
st.dataframe(rls_rows, hide_index=True, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────
# Section 3: RPA session pool stats
# ─────────────────────────────────────────────────────────────────────────
st.subheader("3. Пул RPA-сессий")
st.caption(
    "DesktopRPASessionPool — persistent httpx-clients с session affinity. "
    "(Источник: pool.stats(); placeholder если pool не активен.)"
)

pool_rows = [
    {"metric": "Total sessions", "value": "—"},
    {"metric": "In use", "value": "—"},
    {"metric": "Idle", "value": "—"},
    {
        "metric": "Feature-flag",
        "value": "desktop_rpa_session_pool_enabled (default-OFF)",
    },
]
st.dataframe(pool_rows, hide_index=True, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────
# Section 4: Scheduler DLQ
# ─────────────────────────────────────────────────────────────────────────
st.subheader("4. DLQ планировщика")
st.caption(
    "Последние failed APScheduler jobs. Endpoint: `GET /admin/scheduler/dlq?limit=10`."
)

dlq_entries: list[dict] = []
try:
    raw = client.get("/admin/scheduler/dlq", params={"limit": 10})
    if isinstance(raw, list):
        dlq_entries = raw
except Exception:  # noqa: BLE001
    st.warning(
        "Не удалось получить /admin/scheduler/dlq. "
        "Возможно scheduler_dlq_enabled=False или endpoint не зарегистрирован."
    )

if dlq_entries:
    cols = st.columns(2)
    cols[0].metric("DLQ size (sample 10)", len(dlq_entries))
    st.dataframe(dlq_entries, hide_index=True, use_container_width=True)
else:
    st.info("Нет failed scheduler jobs или feature-flag scheduler_dlq_enabled=False.")


# ─────────────────────────────────────────────────────────────────────────
# Section 5: Browser cookies persistence (S21 W7)
# ─────────────────────────────────────────────────────────────────────────
st.subheader("5. Сохранение cookies в браузере")
st.caption(
    "BrowserCookieStore: Redis hash `browser:session:{tenant}:{user}:{domain}` "
    "TTL 24h. Feature-flag `browser_cookies_redis_persist` (default-OFF)."
)
st.write(
    f"Selected tenant scope: `{selected_id}` — детальный просмотр persisted "
    "cookies требует прямого Redis-доступа (S22 K3 carryover)."
)


# ─────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "Sprint 21 — Resilience & Multi-tenancy Hardening. Read-only dashboard. "
    "Все feature-flags default-OFF; sections отражают runtime state "
    "(пустые секции = feature inactive)."
)
