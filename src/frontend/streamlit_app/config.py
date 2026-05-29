"""Centralized frontend configuration.

Single source of truth for all Streamlit frontend settings.
All other modules import from here instead of duplicating values.
"""

from __future__ import annotations

import os

# ── API ────────────────────────────────────────────────────────────────────────

_API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
"""Base URL for all backend API calls."""


def get_api_base_url() -> str:
    return _API_BASE_URL


# ── Timeouts (seconds) ────────────────────────────────────────────────────────

API_TIMEOUT_SHORT: float = 5.0
"""Quick checks, health pings."""

API_TIMEOUT_MEDIUM: float = 15.0
"""Standard CRUD operations."""

API_TIMEOUT_LONG: float = 30.0
"""Heavy operations (workflows, bulk actions)."""

API_TIMEOUT_RAG: float = 60.0
"""AI/RAG operations requiring longer wait."""


# ── Feature flags (frontend-only) ─────────────────────────────────────────────

ENABLE_ADMIN_REACT: bool = os.environ.get("ENABLE_ADMIN_REACT", "1") == "1"
"""Render admin-react tab in sidebar when True."""
