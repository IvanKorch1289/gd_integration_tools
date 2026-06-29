"""Streamlit UI config — central place for tunable constants.

All magic numbers that appear 3+ times across pages belong here.
Per-page one-off values stay local.
"""
from __future__ import annotations


class StreamlitConfig:
    """Centralized UI constants for Streamlit pages.

    Use these instead of magic numbers to make tuning centralized.
    Override via env vars (STREAMLIT_CONFIG_*) at runtime if needed.
    """

    # === HTTP / API client ===
    HTTP_TIMEOUT_SEC: float = 10.0
    HTTP_TIMEOUT_LONG_SEC: float = 30.0

    # === Search / pagination limits ===
    SEARCH_DEFAULT_LIMIT: int = 20
    SEARCH_MIN_LIMIT: int = 1
    SEARCH_MAX_LIMIT: int = 200

    # === Audit / DSL usage ===
    AUDIT_DEFAULT_LIMIT: int = 50
    AUDIT_MIN_LIMIT: int = 1
    AUDIT_MAX_LIMIT: int = 1000

    # === Size limits (terms aggregation) ===
    TERMS_DEFAULT_SIZE: int = 10
    TERMS_MIN_SIZE: int = 1
    TERMS_MAX_SIZE: int = 100

    # === Workflow timeouts ===
    WORKFLOW_EVENTS_LIMIT: int = 100

    # === UI dimensions ===
    TEXT_AREA_DEFAULT_HEIGHT: int = 200
    DATAFRAME_DEFAULT_HEIGHT: int = 500
    CODE_BLOCK_HEIGHT: int = 120

    # === Auto-refresh intervals (for st.fragment run_every) ===
    REFRESH_LIVE_LOGS_SEC: int = 2
    REFRESH_HEALTHCHECK_SEC: int = 5
    REFRESH_QUEUES_SEC: int = 10
    REFRESH_AUDIT_DSL_SEC: int = 30

    # === Form defaults ===
    TEXT_INPUT_DEFAULT_VALUE: str = ""
    NUMBER_INPUT_STEP_1: int = 1


# Singleton instance for convenience
config = StreamlitConfig()
