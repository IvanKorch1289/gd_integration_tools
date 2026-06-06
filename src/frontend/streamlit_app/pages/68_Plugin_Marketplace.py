"""Plugin Marketplace — admin-страница V11-плагинов (Sprint 3).

Источник данных: ``GET /api/v1/plugins/inventory`` (см.
:mod:`src.backend.entrypoints.api.v1.endpoints.v11_inventory`).

Возможности:

* список загруженных / отклонённых / упавших плагинов;
* фильтр по status (loaded / failed / skipped);
* detail-panel с capabilities, provides, requires_core, причиной отказа;
* link на исходный ``plugin.toml`` (read-only).
* **Sprint 14 K5 W3**: вкладка ``Dependency Graph`` с Mermaid-рендером
  графа зависимостей (``compatibility.requires_plugins``).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page('Plugin Marketplace', ':electric_plug:')
st.header("Plugin Marketplace (V11)")
st.caption(
    "Inventory загруженных в-tree плагинов из ``extensions/<name>/`` "
    "(см. ADR-042). Данные — ``/api/v1/plugins/inventory``."
)

client = get_api_client()
inventory = client.get_plugins_inventory()

if not inventory.get("enabled", False):
    reason = inventory.get("reason") or "loader выключен"
    st.warning(f"V11 Plugin Loader недоступен: {reason}")
    st.stop()

plugins: list[dict] = inventory.get("plugins", [])
if not plugins:
    st.info("Нет загруженных V11-плагинов. Добавьте каталог в ``extensions/<name>/``.")
    st.stop()


# ────────────── Top metrics ──────────────────────────────────────────

status_counts: dict[str, int] = {"loaded": 0, "failed": 0, "skipped": 0}
for p in plugins:
    status_counts[p.get("status", "?")] = status_counts.get(p.get("status", "?"), 0) + 1

col_total, col_loaded, col_failed, col_skipped = st.columns(4)
col_total.metric("Всего", len(plugins))
col_loaded.metric("Loaded", status_counts.get("loaded", 0))
col_failed.metric("Failed", status_counts.get("failed", 0))
col_skipped.metric("Skipped", status_counts.get("skipped", 0))

st.divider()


# ────────────── Filters + table ──────────────────────────────────────

status_filter = st.multiselect(
    "Status",
    options=("loaded", "failed", "skipped"),
    default=("loaded", "failed", "skipped"),
    help="Фильтрация по статусу load-этапа",
)

filtered = [p for p in plugins if p.get("status") in status_filter]

if not filtered:
    st.info("Под выбранные фильтры ничего не подходит.")
    st.stop()


# ────────────── Sprint 14 K5 W3: tabs (Inventory / Dependency Graph) ─

tabs = st.tabs(["Inventory", "Dependency Graph"])


def _short(items: list[str], limit: int = 3) -> str:
    if not items:
        return "—"
    head = ", ".join(items[:limit])
    return f"{head}…(+{len(items) - limit})" if len(items) > limit else head


rows = []
for plugin in filtered:
    provides = plugin.get("provides") or {}
    rows.append(
        {
            "name": plugin.get("name"),
            "version": plugin.get("version", "—"),
            "status": plugin.get("status"),
            "requires_core": plugin.get("requires_core", "—"),
            "tenant_aware": plugin.get("tenant_aware", False),
            "capabilities": _short(plugin.get("capabilities") or []),
            "actions": _short(provides.get("actions") or []),
            "sources": _short(provides.get("sources") or []),
            "sinks": _short(provides.get("sinks") or []),
            "reason": plugin.get("reason") or "—",
        }
    )

with tabs[0]:
    st.dataframe(rows, use_container_width=True, hide_index=True)

with tabs[1]:
    st.markdown("### Граф зависимостей плагинов")
    st.caption(
        "Mermaid-визуализация ``compatibility.requires_plugins`` (Sprint 14 K5 W3)."
    )
    graph = client.get_dependency_graph()
    if graph.get("error"):
        st.warning(f"Backend недоступен: {graph['error']}")
    elif not graph.get("nodes"):
        st.info("Нет плагинов или связей в графе.")
    else:
        diagram = ["graph LR"]
        for node in graph["nodes"]:
            label = f"{node['id']}\\n{node.get('version', '?')}"
            diagram.append(f'    {node["id"]}["{label}"]')
        for edge in graph["edges"]:
            diagram.append(
                f"    {edge['source']} -->|{edge.get('spec', '?')}| {edge['target']}"
            )
        st.code("\n".join(diagram), language="mermaid")


# ────────────── Detail panel ─────────────────────────────────────────

st.subheader("Детали плагина")
names = [p["name"] for p in filtered]
selected_name = st.selectbox("Плагин", options=names, index=0)

selected = next((p for p in filtered if p["name"] == selected_name), None)
if selected is None:
    st.stop()
assert selected is not None  # noqa: S101

col_meta, col_lists = st.columns([1, 2])

with col_meta:
    st.markdown(f"**Имя:** `{selected['name']}`")
    st.markdown(f"**Версия:** `{selected.get('version', '—')}`")
    st.markdown(f"**Status:** `{selected['status']}`")
    st.markdown(f"**requires_core:** `{selected.get('requires_core', '—')}`")
    st.markdown(f"**tenant_aware:** `{selected.get('tenant_aware', False)}`")
    if selected.get("description"):
        st.markdown(f"**Описание:** {selected['description']}")
    if selected.get("reason"):
        st.warning(f"reason: {selected['reason']}")
    manifest_path = selected.get("manifest_path")
    if manifest_path:
        st.code(manifest_path, language=None)

with col_lists:
    capabilities = selected.get("capabilities") or []
    if capabilities:
        st.markdown("**Capabilities**")
        for cap in capabilities:
            st.markdown(f"- `{cap}`")
    else:
        st.markdown("**Capabilities**: —")

    provides = selected.get("provides") or {}
    if any(provides.values()):
        st.markdown("**Provides**")
        for kind, items in provides.items():
            if items:
                with st.expander(f"{kind} ({len(items)})", expanded=False):
                    for item in items:
                        st.markdown(f"- `{item}`")
    else:
        st.markdown("**Provides**: —")
