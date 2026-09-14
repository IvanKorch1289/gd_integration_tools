"""Route & Connector Registry Explorer — Wave 2 DX #54 (Sprint 175).

Просмотр и поиск routes/connectors/actions через ``RegistryExplorer``
из ``core.registry_explorer``.

Возможности:
- Загрузка routes/connectors/actions из backend API inventory.
- Поиск по tag / owner / category / source.
- Drill-down в выбранный route.
- Inline stats: totals, by-owner, by-category.

Pure-Python data layer (RegistryExplorer) подключён к UI через
``api_clients.inventory`` + ``core.registry_explorer`` helpers.
"""

from __future__ import annotations

import polars as pl
import streamlit as st

from src.backend.core.registry_explorer import (
    ConnectorEntry,
    RegistryExplorer,
    RouteEntry,
    get_registry_explorer,
)
from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page(layout="wide")

st.header("Реестр маршрутов / коннекторов / actions")


def _get_client():
    """Lazy API client getter (allows test patching via patch.object)."""
    return get_api_client()


# ─── In-process explorer (для filter/search/groupBy) ───
explorer: RegistryExplorer = get_registry_explorer()


def _seed_explorer() -> None:
    """Seed explorer из API inventory responses."""
    explorer.clear()
    try:
        client = _get_client()
        routes_inv = client.get_routes_inventory()
        for r in routes_inv.get("routes", []) or []:
            tags = tuple(r.get("tags", []) or [])
            explorer.register_route(
                RouteEntry(
                    id=str(r.get("route_id", "")),
                    source=str(r.get("source", "")),
                    description=str(r.get("description", "")),
                    owner=str(r.get("owner", "")),
                    timeout_seconds=float(r.get("timeout_seconds", 30.0)),
                    tags=tags,
                    tenant_id=str(r.get("tenant_id", "*")),
                )
            )
    except Exception as exc:  # broad — network/timeout/parse
        st.warning(f"Не удалось загрузить routes inventory: {exc}")

    try:
        from src.frontend.streamlit_app.api_clients.inventory import InventoryClient

        ic = InventoryClient()
        plugins_inv = ic.get_plugins_inventory()
        for p in plugins_inv.get("plugins", []) or []:
            cat = str(p.get("category", "other"))
            auth = str(p.get("auth", ""))
            explorer.register_connector(
                ConnectorEntry(
                    name=str(p.get("name", "")),
                    category=cat,
                    auth=auth,
                    description=str(p.get("description", "")),
                )
            )
    except Exception as exc:  # broad — optional connector registry
        st.info(f"Connectors inventory недоступен: {exc}")


# ─── Refresh ───
col1, col2, col3 = st.columns([1, 1, 4])
if col1.button("🔄 Обновить реестр"):
    with st.spinner("Загрузка..."):
        _seed_explorer()
    st.rerun()

# Auto-seed on first load.
if explorer.route_count() == 0:
    _seed_explorer()

# ─── Summary metrics ───
summary = explorer.summary()
metric_cols = st.columns(4)
metric_cols[0].metric("Routes", summary["routes"])
metric_cols[1].metric("Connectors", summary["connectors"])
metric_cols[2].metric("Actions", summary["actions"])
# Count distinct owners via the to_dict export (no local var needed).
_distinct_owners = {e["owner"] for e in explorer.to_dict()["routes"] if e.get("owner")}
metric_cols[3].metric("Owners", len(_distinct_owners))

st.divider()

# ─── Routes tab ───
tab_routes, tab_connectors, tab_actions = st.tabs(
    ["🛤 Routes", "🔌 Connectors", "⚡ Actions"]
)

with tab_routes:
    st.subheader("Маршруты (с фильтрацией)")
    routes = explorer.list_routes()
    if not routes:
        st.info("Нет маршрутов. Нажмите «Обновить реестр».")
    else:
        # Filters.
        fcol1, fcol2, fcol3 = st.columns(3)
        all_owners = sorted({r.owner for r in routes if r.owner})
        all_tags = sorted({t for r in routes for t in r.tags})

        owner_filter = fcol1.selectbox("Owner", ["(all)"] + all_owners, key="reg_owner")
        tag_filter = fcol2.multiselect("Tags", all_tags, key="reg_tags")
        search = fcol3.text_input("Search by id", key="reg_search")

        filtered = routes
        if owner_filter != "(all)":
            filtered = [r for r in filtered if r.owner == owner_filter]
        if tag_filter:
            filtered = [r for r in filtered if all(t in r.tags for t in tag_filter)]
        if search:
            s = search.lower()
            filtered = [
                r for r in filtered if s in r.id.lower() or s in r.source.lower()
            ]

        st.caption(f"Найдено: {len(filtered)} из {len(routes)}")

        if filtered:
            df = pl.DataFrame(
                [
                    {
                        "id": r.id,
                        "source": r.source,
                        "owner": r.owner or "—",
                        "timeout_s": r.timeout_seconds,
                        "tags": ", ".join(r.tags) or "—",
                        "tenant": r.tenant_id,
                    }
                    for r in filtered
                ]
            )
            st.dataframe(df, width="stretch", height=400)

            # Owner breakdown.
            st.caption("By owner:")
            by_owner: dict[str, int] = {}
            for r in filtered:
                by_owner[r.owner or "(none)"] = by_owner.get(r.owner or "(none)", 0) + 1
            owner_df = pl.DataFrame(
                [
                    {"owner": k, "count": v}
                    for k, v in sorted(by_owner.items(), key=lambda x: -x[1])
                ]
            )
            st.dataframe(owner_df, width="stretch", height=200)

            # Drill-down.
            with st.expander("Drill-down (детали маршрута)"):
                sel_id = st.selectbox(
                    "Route ID", [r.id for r in filtered], key="reg_route_sel"
                )
                sel = next((r for r in filtered if r.id == sel_id), None)
                if sel:
                    st.json(
                        {
                            "id": sel.id,
                            "source": sel.source,
                            "description": sel.description,
                            "owner": sel.owner,
                            "timeout_seconds": sel.timeout_seconds,
                            "tags": list(sel.tags),
                            "tenant_id": sel.tenant_id,
                        }
                    )

with tab_connectors:
    st.subheader("Коннекторы")
    connectors = explorer.list_connectors()
    if not connectors:
        st.info("Нет коннекторов.")
    else:
        ccol1, ccol2 = st.columns(2)
        all_cats = sorted({con.category for con in connectors if con.category})
        all_auths = sorted({con.auth for con in connectors if con.auth})

        cat_filter = ccol1.multiselect("Category", all_cats, key="reg_cats")
        auth_filter = ccol2.multiselect("Auth", all_auths, key="reg_auths")

        connectors_filtered: list[ConnectorEntry] = list(connectors)
        if cat_filter:
            connectors_filtered = [
                con for con in connectors_filtered if con.category in cat_filter
            ]
        if auth_filter:
            connectors_filtered = [
                con for con in connectors_filtered if con.auth in auth_filter
            ]

        st.caption(f"Найдено: {len(connectors_filtered)} из {len(connectors)}")
        if connectors_filtered:
            df = pl.DataFrame(
                [
                    {
                        "name": con.name,
                        "category": con.category or "—",
                        "auth": con.auth or "—",
                        "description": con.description or "—",
                    }
                    for con in connectors_filtered
                ]
            )
            st.dataframe(df, width="stretch", height=400)

with tab_actions:
    st.subheader("Actions")
    actions = explorer.list_actions()
    if not actions:
        st.info(
            "Нет actions в реестре. Действия регистрируются через core.registry_explorer."
        )
    else:
        df = pl.DataFrame(
            [
                {
                    "name": a.name,
                    "side_effect": a.side_effect or "—",
                    "owner": a.owner or "—",
                    "params": ", ".join(a.params) or "—",
                }
                for a in actions
            ]
        )
        st.dataframe(df, width="stretch", height=400)

related_pages_footer(current_key="90_Реестр_Маршрутов")
