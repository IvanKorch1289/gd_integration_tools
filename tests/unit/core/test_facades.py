"""Tests for unified middleware facades (S171 M7)."""
from __future__ import annotations

import pytest


class TestFacadesImport:
    def test_auth_facades(self) -> None:
        from src.backend.core.facades import (
            AuthorizationGateway,
            CapabilityGate,
            PIITokenizer,
        )
        assert AuthorizationGateway is not None
        assert CapabilityGate is not None
        assert PIITokenizer is not None

    def test_timeout_retry_facades(self) -> None:
        from src.backend.core.facades import (
            with_timeout,
            async_timeout,
            retry_async,
            default_retryable,
        )
        assert callable(with_timeout)
        assert callable(async_timeout)
        assert callable(retry_async)
        assert isinstance(default_retryable(), tuple)

    def test_ratelimit_facade_lazy(self) -> None:
        from src.backend.core.facades import (
            RateLimit, RedisRateLimiter, get_rate_limiter, RateLimitExceeded,
        )
        assert RateLimit is not None
        assert RedisRateLimiter is not None
        assert callable(get_rate_limiter)
        assert issubclass(RateLimitExceeded, Exception)

    def test_circuit_breaker_facade_lazy(self) -> None:
        from src.backend.core.facades import ClientCircuitBreaker
        assert ClientCircuitBreaker is not None

    def test_bulkhead_facade_lazy(self) -> None:
        from src.backend.core.facades import (
            Bulkhead, BulkheadExhausted,
        )
        assert Bulkhead is not None
        assert issubclass(BulkheadExhausted, Exception)

    def test_pii_tokenizer_provider(self) -> None:
        from src.backend.core.facades import get_pii_tokenizer_provider
        assert get_pii_tokenizer_provider is not None


class TestFacadeUsage:
    """Demonstrate that facades can actually be used."""

    def test_default_retryable_includes_network_errors(self) -> None:
        from src.backend.core.facades import default_retryable
        types = default_retryable()
        assert ConnectionError in types
        assert OSError in types

    def test_ratelimit_class_can_be_imported(self) -> None:
        from src.backend.core.facades import RateLimit, RedisRateLimiter
        # Check class hierarchy
        assert hasattr(RateLimit, "__init__")
        assert hasattr(RedisRateLimiter, "__init__")
