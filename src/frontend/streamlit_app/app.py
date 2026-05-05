"""GD Integration Tools — Streamlit Dashboard.

Главная страница: KPI метрики + Component Health.
"""

import sys
from pathlib import Path

import streamlit as st

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(
    page_title="GD Integration Tools",
    page_icon=":bank:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────── Header с логотипом ────────────

col_title, col_logo = st.columns([8, 1])
with col_title:
    st.title("GD Integration Tools")
    st.caption("Enterprise Integration Bus — Dashboard")
with col_logo:
    logo_path = _project_root / "src" / "static" / "images" / "kuban_credit_logo.svg"
    if logo_path.exists():
        st.image(str(logo_path), width=120)

# ──────────── Метрики ────────────

client = get_api_client()

try:
    metrics = client.get_metrics()
except Exception:
    metrics = {}

if metrics:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("DSL Routes", metrics.get("routes_total", 0))
    c2.metric("Actions", metrics.get("actions_count", 0))
    c3.metric("Enabled", metrics.get("routes_enabled", 0))
    c4.metric("Disabled (FF)", metrics.get("routes_disabled", 0))
    c5.metric("Services", len(metrics.get("services", [])))
    c6.metric("Feature Flags", len(metrics.get("feature_flags_disabled", [])))
else:
    st.warning("Не удалось загрузить метрики. Проверьте подключение к backend.")

# ──────────── Component Health ────────────

st.subheader("Component Health")

try:
    health = client.get_health()
except Exception:
    health = {}

if health:
    cols = st.columns(min(len(health), 4))
    for i, (name, status) in enumerate(health.items()):
        with cols[i % len(cols)]:
            if status:
                st.success(f"✓ {name}")
            else:
                st.error(f"✗ {name}")
else:
    st.info("Health данные недоступны.")

# ──────────── Auto-refresh ────────────

st.divider()
col_refresh, col_interval = st.columns([1, 3])
with col_refresh:
    if st.button("Обновить"):
        st.rerun()
with col_interval:
    st.caption("Данные обновляются при нажатии «Обновить» или перезагрузке страницы.")
