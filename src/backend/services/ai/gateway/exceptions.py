"""Исключения LiteLLM-шлюза.

Canonical location: core.ai.errors
Этот модуль предоставляет backward-compat re-export.
"""

from __future__ import annotations

from src.backend.core.ai.errors import (  # noqa: F401
    GatewayError,
    GatewayRateLimited,
    GatewayUnavailable,
)

__all__ = ("GatewayError", "GatewayRateLimited", "GatewayUnavailable")
