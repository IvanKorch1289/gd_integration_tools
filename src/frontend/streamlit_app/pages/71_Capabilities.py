"""К5 (Wave K5/docs-tenants-caps) — admin-страница capabilities heatmap.

Источник данных:

* ``GET /api/v1/admin/capabilities`` — vocabulary + DEFAULT_CAPABILITY_CATALOG;
* ``GET /api/v1/admin/capabilities/audit-events`` — recent denied;
* ``GET /api/v1/plugins/inventory`` — plugin × capability матрица.

Heatmap: plugin × capability с цветом по статусу (granted / denied / not requested).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="Capabilities", page_icon="🔐", layout="wide")
st.header("Capability Matrix")
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
cols[0].metric("Capabilities", len(vocab))
cols[1].metric("Plugins", len(plugins))
cols[2].metric("Public caps", sum(1 for c in vocab if c.get("public")))

st.divider()

# ────────────── Heatmap ─────────────────────────────────────────────

if vocab and plugins:
    st.subheader("Plugin × Capability matrix")

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

st.divider()

# ────────────── Recent denied events ────────────────────────────────

with st.expander("Recent denied capability events"):
    audit = client.get_audit_events(event_type="capability_denied", limit=50)
    events = audit.get("events") or []
    if events:
        st.dataframe(events, use_container_width=True, hide_index=True)
    else:
        st.write(
            "_(нет denied событий — capability-gate не отклонил ни одной "
            "проверки за последние 50 записей audit log)_"
        )

st.divider()

# ────────────── Vocabulary table ────────────────────────────────────

with st.expander("Полный vocabulary (ADR-044)"):
    if vocab:
        st.dataframe(vocab, use_container_width=True, hide_index=True)
    else:
        st.write("_(vocabulary недоступен)_")
