"""Общие компоненты для всех страниц."""

from __future__ import annotations

from src.frontend.streamlit_app.shared.components import (
    dataframe_view,
    metric_row,
    setup_page,
)
from src.frontend.streamlit_app.shared.constants import (
    PROCESSOR_COLORS,
    PROCESSOR_ICONS,
    VISUAL_PROCESSORS,
)
from src.frontend.streamlit_app.shared.utils import (
    chunked,
    format_bytes,
    format_duration,
    sanitize_label,
)

__all__ = [
    "VISUAL_PROCESSORS",
    "PROCESSOR_ICONS",
    "PROCESSOR_COLORS",
    "sanitize_label",
    "format_bytes",
    "format_duration",
    "chunked",
    "setup_page",
    "metric_row",
    "dataframe_view",
]
