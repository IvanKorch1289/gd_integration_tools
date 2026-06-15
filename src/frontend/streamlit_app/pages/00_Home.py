"""Главная страница — навигация и mapping старых закладок (Wave 10.1).

S142 W2: PoC regrouping. Content moved to
``_groups/home/home_page/navigation.py``. This file is now a thin shim
that re-exports and calls ``render_home()`` to preserve Streamlit
auto-discovery (Streamlit scans for ``*.py`` directly under ``pages/``).

Reference pattern: ``_groups/dsl/dsl_templates/`` (S142 W1 PoC).
"""

from __future__ import annotations

# S142 W2: PoC — re-export from regrouped sub-package. Streamlit
# auto-discovers this .py file; render_home() is the actual entry.
from src.frontend.streamlit_app.pages._groups.home.home_page import render_home

__all__ = ("render_home",)
