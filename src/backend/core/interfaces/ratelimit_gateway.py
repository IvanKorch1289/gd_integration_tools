"""RateLimitGateway — alias for RateLimitChecker Protocol.

This module provides a public alias for the RateLimitChecker Protocol
defined in the middlewares module, enabling consistent gateway naming
across the codebase.
"""

from __future__ import annotations

# Re-export the Protocol and config from the middlewares module
from src.backend.entrypoints.middlewares.global_ratelimit import (
    RateLimitChecker,
    RateLimitConfig,
)

# Public alias following gateway naming convention
RateLimitGateway = RateLimitChecker

__all__ = ("RateLimitGateway", "RateLimitChecker", "RateLimitConfig")
