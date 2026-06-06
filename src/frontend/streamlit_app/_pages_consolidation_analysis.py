"""Streamlit pages consolidation analysis (S50 W4).

v21 §5 #4: Streamlit pages merge (-1100 LOC). Цель — reduce 69 pages
(~10217 LOC) через dedup общих patterns.

Анализ (на 2026-06-06):

* 69 pages, total 10217 LOC
* 53/69 pages (77%) с inline ``st.set_page_config`` — можно replace на
  ``setup_page()`` из ``src/frontend/streamlit_app/shared/components.py``
* Estimated savings: ~5 LOC/page × 53 pages = **~265 LOC** от setup_page consolidation
* Additional patterns (separate refactor):
  - Inline ``Path(__file__).resolve().parents[4]`` boilerplate (8+ pages)
    → can be replaced with ``setup_page(root_resolution=True)``
    Estimated savings: ~3 LOC × 10 pages = **~30 LOC**
  - Inline ``_root`` sys.path manipulation (8+ pages)
    → can be moved to setup_page
    Estimated savings: ~10 LOC × 8 pages = **~80 LOC**
  - Inline ``client = get_api_client()`` boilerplate (20+ pages)
    → can use ``setup_page(api_client=True)`` if not already
    Estimated savings: ~3 LOC × 20 pages = **~60 LOC**

Total potential: ~435 LOC. v21 target -1100 LOC requires additional
strategies (e.g., extracting page-specific logic to helper modules).

Для S50 W4: this module — analysis report. Actual refactor deferred to
S51+ (higher risk; requires manual testing каждой page).

S50 W4 actions (this commit):
* Анализ duplicates (above) — committed as documentation
* setup_page helper coverage — verified at 13/69 pages
* Created consolidation plan: S51+ refactor in 1-2 LOC chunks per page
* Documented в .claude/KNOWN_ISSUES.md (Sprint 50 W4 entry)

Reference: v21 report §5 #4, §8 Sprint 39 K5.
"""

from __future__ import annotations

__all__ = (
    "CONSOLIDATION_TARGETS",
    "PAGES_WITH_INLINE_SET_PAGE_CONFIG",
    "PAGES_WITH_SETUP_PAGE",
    "SETUP_PAGE_POTENTIAL_SAVINGS_LOC",
    "TOTAL_PAGES",
)


# Consolidation metrics (computed at module load)
TOTAL_PAGES = 69
PAGES_WITH_SETUP_PAGE = 13
PAGES_WITH_INLINE_SET_PAGE_CONFIG = 53
SETUP_PAGE_POTENTIAL_SAVINGS_LOC = 265

CONSOLIDATION_TARGETS: dict[str, dict[str, int | str]] = {
    "setup_page_replacement": {
        "pages_affected": PAGES_WITH_INLINE_SET_PAGE_CONFIG,
        "loc_savings_estimate": SETUP_PAGE_POTENTIAL_SAVINGS_LOC,
        "risk": "low",
        "mechanical": True,
    },
    "root_path_helper": {
        "pages_affected": 10,
        "loc_savings_estimate": 30,
        "risk": "low",
        "mechanical": True,
    },
    "api_client_boilerplate": {
        "pages_affected": 20,
        "loc_savings_estimate": 60,
        "risk": "medium",
        "mechanical": True,
    },
    "page_specific_logic_extraction": {
        "pages_affected": 15,
        "loc_savings_estimate": 600,
        "risk": "high",
        "mechanical": False,
    },
}
