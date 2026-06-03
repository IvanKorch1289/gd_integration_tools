"""Unit tests for src.backend.core.interfaces.ratelimit_gateway."""

from __future__ import annotations

from src.backend.core.interfaces.ratelimit_gateway import (
    RateLimitChecker,
    RateLimitConfig,
    RateLimitGateway,
)


class TestRateLimitGateway:
    def test_is_alias(self) -> None:
        assert RateLimitGateway is RateLimitChecker

    def test_exports(self) -> None:
        assert RateLimitConfig is not None
        assert RateLimitChecker is not None
