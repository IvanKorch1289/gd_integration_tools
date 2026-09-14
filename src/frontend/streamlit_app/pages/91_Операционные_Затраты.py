"""Operational Cost Attribution Dashboard (Wave 4 #75).

In-process UI поверх ``core.cost_attribution.CostAttribution``:
- ``@track_cost`` decorator на любой function → запись в registry.
- Здесь: live dashboard с breakdown по tenant / route / resource / agent.
- Top consumers, экспорт отчёта, drill-down.

Чистый pure-Python data layer (``get_cost_registry()``) — без backend API,
без network. Тестируется через unit-тесты core модуля.
"""

from __future__ import annotations

import polars as pl
import streamlit as st

from src.backend.core.cost_attribution import (
    CostAttribution,
    CostRecord,
    get_cost_registry,
)
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page(layout="wide")

st.header("Операционные cost attribution (per-tenant / route / agent)")


def _get_registry() -> CostAttribution:
    """Lazy getter для testability."""
    return get_cost_registry()


def _format_currency(value: float) -> str:
    """Format USD value."""
    if value < 0.01:
        return f"${value:.6f}"
    if value < 1.0:
        return f"${value:.4f}"
    return f"${value:.2f}"


# ─── Summary metrics ───
registry = _get_registry()
records = registry.list_records()
total_cost = sum(r.cost_usd for r in records)
total_units = sum(r.units for r in records)

metric_cols = st.columns(4)
metric_cols[0].metric("Записей", len(records))
metric_cols[1].metric("Total cost", _format_currency(total_cost))
metric_cols[2].metric("Total units", f"{total_units:.1f}")
distinct_tenants = {r.tenant_id for r in records}
metric_cols[3].metric("Tenants", len(distinct_tenants))

st.divider()

if not records:
    st.info(
        "Нет записей. Используйте ``@track_cost`` decorator на function "
        "для автоматической регистрации. Пример:\n\n"
        "```python\n"
        "from src.backend.core.cost_attribution import track_cost, "
        "ResourceType\n\n"
        "@track_cost(ResourceType.LLM_TOKENS, cost_per_unit=0.0001, "
        "tenant_id_arg='tenant_id')\n"
        "async def my_api_call(tenant_id: str, tokens: int):\n"
        "    return ...\n"
        "```"
    )
    related_pages_footer(current_key="91_Операционные_Затраты")
    st.stop()

# ─── Tabs ───
tab_breakdown, tab_top, tab_table, tab_export = st.tabs(
    [
        "📊 Breakdown",
        "🏆 Top consumers",
        "📋 All records",
        "💾 Export",
    ]
)

with tab_breakdown:
    st.subheader("By tenant")
    by_tenant: dict[str, float] = {}
    for r in records:
        by_tenant[r.tenant_id] = by_tenant.get(r.tenant_id, 0.0) + r.cost_usd
    tenant_df = pl.DataFrame(
        [
            {"tenant_id": t, "cost_usd": v}
            for t, v in sorted(by_tenant.items(), key=lambda x: -x[1])
        ]
    )
    st.dataframe(tenant_df, width="stretch")
    st.bar_chart(tenant_df, x="tenant_id", y="cost_usd")

    st.subheader("By resource type")
    by_resource: dict[str, float] = {}
    for r in records:
        key = r.resource_type.value
        by_resource[key] = by_resource.get(key, 0.0) + r.cost_usd
    res_df = pl.DataFrame(
        [
            {"resource": k, "cost_usd": v}
            for k, v in sorted(by_resource.items(), key=lambda x: -x[1])
        ]
    )
    st.dataframe(res_df, width="stretch")
    st.bar_chart(res_df, x="resource", y="cost_usd")

with tab_top:
    st.subheader("Top consumers (tenant × route × agent)")
    top_df_data = []
    pairs: dict[tuple[str, str, str], float] = {}
    units: dict[tuple[str, str, str], float] = {}
    for r in records:
        key = (r.tenant_id, r.route_id, r.agent or "(no-agent)")
        pairs[key] = pairs.get(key, 0.0) + r.cost_usd
        units[key] = units.get(key, 0.0) + r.units
    for (t, r_id, a), cost in sorted(pairs.items(), key=lambda x: -x[1])[:20]:
        top_df_data.append(
            {
                "tenant_id": t,
                "route_id": r_id,
                "agent": a,
                "cost_usd": cost,
                "units": units[(t, r_id, a)],
            }
        )
    if top_df_data:
        st.dataframe(pl.DataFrame(top_df_data), width="stretch", height=500)
    else:
        st.info("Нет данных.")

with tab_table:
    st.subheader("Все записи (chronological)")
    table_df = pl.DataFrame(
        [
            {
                "timestamp": r.timestamp,
                "tenant_id": r.tenant_id,
                "route_id": r.route_id,
                "resource": r.resource_type.value,
                "units": r.units,
                "cost_usd": r.cost_usd,
                "agent": r.agent or "—",
            }
            for r in sorted(records, key=lambda x: -x.timestamp)
        ]
    )
    st.dataframe(table_df, width="stretch", height=500)

with tab_export:
    st.subheader("Export")
    st.caption(
        "Экспорт в JSON для отчётов / billing integration. "
        "Файл содержит все records + aggregations."
    )
    export_payload = {
        "summary": {
            "total_cost_usd": total_cost,
            "total_units": total_units,
            "record_count": len(records),
        },
        "by_tenant": by_tenant,
        "by_resource": by_resource,
        "by_route": {
            r.route_id: by_route.get(r.route_id, 0.0) + r.cost_usd
            for r in records
            for by_route in [
                {r.route_id: sum(rr.cost_usd for rr in records if rr.route_id == r.route_id)}
            ]
            for k, v in by_route.items()
        }.copy() if records else {},
        "records": [r.to_dict() for r in records],
    }
    # Simpler: use to_dict from registry-style aggregation.
    from src.backend.core.cost_attribution import CostReport
    rep = CostReport(
        timestamp=__import__("time").time(), records=records
    )
    st.json(rep.to_dict())

    st.download_button(
        "📥 Download cost-report.json",
        data=__import__("json").dumps(rep.to_dict(), indent=2),
        file_name="cost-report.json",
        mime="application/json",
    )

related_pages_footer(current_key="91_Операционные_Затраты")
