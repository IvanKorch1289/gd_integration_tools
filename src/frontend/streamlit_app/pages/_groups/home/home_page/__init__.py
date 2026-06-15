"""Home page sub-package (S142 W2 PoC).

Extracts content from ``pages/00_Home.py`` (75 lines, navigation/redirects
only) into a per-page sub-package following the same pattern as
``_groups/dsl/dsl_templates/`` (S142 W1).

Sub-modules:
* :mod:`.navigation` — main render function + redirect table.
"""

from __future__ import annotations

from src.frontend.streamlit_app.pages._groups.home.home_page.navigation import (
    render_home,  # S142 W2: PoC entry point
)

__all__ = ("render_home",)
