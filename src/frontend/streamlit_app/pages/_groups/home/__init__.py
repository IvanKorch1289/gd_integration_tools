"""Group ``home`` — Home / Onboarding navigation pages.

Pages (Streamlit file → sub-package):
* 00_Home.py                  → home_page/  [PoC extraction: S142 W2]
* 04_Onboarding.py            → onboarding/  [planned: S142 W3+]
"""

from __future__ import annotations

from src.frontend.streamlit_app.pages._groups.home.home_page import (
    render_home,  # S142 W2: PoC re-export
)

__all__ = ("render_home",)
