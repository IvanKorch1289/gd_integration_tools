"""Переиспользуемые UI-компоненты для Streamlit страниц."""

from __future__ import annotations

from src.frontend.streamlit_app.components.badge import status_badge, health_badge
from src.frontend.streamlit_app.components.table import paginated_table, render_metrics_table
from src.frontend.streamlit_app.components.feedback import success_msg, error_msg, warning_msg, info_msg

__all__ = [
    "status_badge",
    "health_badge",
    "paginated_table",
    "render_metrics_table",
    "success_msg",
    "error_msg",
    "warning_msg",
    "info_msg",
]
