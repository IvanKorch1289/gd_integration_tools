"""К5 (Wave K5/docs-tenants-caps) — admin-страница capabilities heatmap.

Источник данных:

* ``GET /api/v1/admin/capabilities`` — vocabulary + DEFAULT_CAPABILITY_CATALOG;
* ``GET /api/v1/admin/capabilities/audit-events`` — recent denied;
* ``GET /api/v1/admin/capabilities/graph`` — Sprint 14 K5 W5 граф;
* ``GET /api/v1/plugins/inventory`` — plugin × capability матрица.

Sprint 14 K5 W5 + K1 W4: добавлены вкладки **Capability Graph** (Mermaid)
и **Audit Log** (grant/deny события).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Возможности", "🔐")
st.header("Матрица возможностей")
st.caption(
    "Каталог capabilities (ADR-044) + plugin × capability heatmap. "
    "Источники — `/api/v1/admin/capabilities` и `/api/v1/plugins/inventory`."
)

client = get_api_client()
catalog = client.get_capability_catalog()
plugins_inv = client.get_plugins_inventory()

vocab = catalog.get("vocabulary") or []
plugins = plugins_inv.get("plugins") or []

cols = st.columns(3)
cols[0].metric("Возможности", len(vocab))
cols[1].metric("Плагины", len(plugins))
cols[2].metric("Публичные", sum(1 for c in vocab if c.get("public")))

st.divider()

tabs = st.tabs(["Матрица", "Граф возможностей", "Журнал аудита", "Словарь"])

# ────────────── Tab 1: Heatmap ─────────────────────────────────────

with tabs[0]:
    if vocab and plugins:
        st.subheader("Матрица Плагин × Возможности")

        cap_names = [c["name"] for c in vocab]
        rows = []
        for plugin in plugins:
            plug_caps = set(plugin.get("capabilities") or [])
            row = {"plugin": plugin.get("name", "?")}
            for cap in cap_names:
                row[cap] = "✅" if cap in plug_caps else "·"
            rows.append(row)
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info(
            "Heatmap пуст: нет vocabulary или нет загруженных плагинов "
            "(ожидает Sprint 3 К1 plugin loader v11)."
        )

# ────────────── Tab 2: Capability Graph (Sprint 14 K5 W5) ──────────

with tabs[1]:
    st.subheader("Граф возможностей")
    st.caption(
        "плагин → возможность → ресурс (Mermaid). Источник — "
        "``/api/v1/admin/capabilities/graph``."
    )
    graph = client.get_capability_graph()
    if graph.get("error"):
        st.warning(f"бэкенд недоступен: {graph['error']}")
    elif not graph.get("nodes"):
        st.info("Нет данных для графа.")
    else:
        diagram = ["graph LR"]
        for node in graph["nodes"]:
            shape_open, shape_close = "[", "]"
            if node["kind"] == "capability":
                shape_open, shape_close = "((", "))"
            elif node["kind"] == "resource":
                shape_open, shape_close = "{{", "}}"
            diagram.append(
                f'    {node["id"].replace(":", "_")}{shape_open}"{node["label"]}"{shape_close}'
            )
        for edge in graph["edges"]:
            label = f"|{edge['label']}|" if edge.get("label") else ""
            diagram.append(
                f"    {edge['source'].replace(':', '_')} -->{label} "
                f"{edge['target'].replace(':', '_')}"
            )
        st.code("\n".join(diagram), language="mermaid")

# ────────────── Tab 3: Audit Log (Sprint 14 K1 W4) ─────────────────

with tabs[2]:
    st.subheader("Журнал аудита возможностей")
    plugin_filter = st.text_input("Фильтр по плагину", "")
    tenant_filter = st.text_input("Фильтр по тенанту", "")
    events = client.get_audit_events(
        plugin=plugin_filter or None, tenant=tenant_filter or None, limit=200
    )
    if events:
        st.dataframe(events, use_container_width=True, hide_index=True)
    else:
        st.info("Нет событий по выбранным фильтрам.")

# ────────────── Tab 4: Vocabulary table ────────────────────────────

with tabs[3]:
    if vocab:
        st.dataframe(vocab, use_container_width=True, hide_index=True)
    else:
        st.write("_(словарь недоступен)_")
