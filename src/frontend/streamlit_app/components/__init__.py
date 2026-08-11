"""Переиспользуемые UI-компоненты для Streamlit страниц."""

from __future__ import annotations

from src.frontend.streamlit_app.components.badge import health_badge, status_badge
from src.frontend.streamlit_app.components.feedback import (
    error_msg,
    info_msg,
    success_msg,
    warning_msg,
)
from src.frontend.streamlit_app.components.table import (
    paginated_table,
    render_metrics_table,
)

__all__ = [
    "error_msg",
    "health_badge",
    "info_msg",
    "paginated_table",
    "render_metrics_table",
    "status_badge",
    "success_msg",
    "warning_msg",
]
