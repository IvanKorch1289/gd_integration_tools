"""Plugin Marketplace — admin-страница V11-плагинов (Sprint 3).

Источник данных: ``GET /api/v1/plugins/inventory`` (см.
:mod:`src.backend.entrypoints.api.v1.endpoints.v11_inventory`).

Возможности:

* список загруженных / отклонённых / упавших плагинов;
* фильтр по status (loaded / failed / skipped);
* detail-panel с capabilities, provides, requires_core, причиной отказа;
* link на исходный ``plugin.toml`` (read-only).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(
    page_title="Plugin Marketplace", page_icon=":electric_plug:", layout="wide"
)
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

st.dataframe(rows, use_container_width=True, hide_index=True)


# ────────────── Detail panel ─────────────────────────────────────────

st.subheader("Детали плагина")
names = [p["name"] for p in filtered]
selected_name = st.selectbox("Плагин", options=names, index=0)

selected = next((p for p in filtered if p["name"] == selected_name), None)
if not selected:
    st.stop()

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
