"""Tests for unified middleware facades (S171 M7)."""
from __future__ import annotations


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
            default_retryable,
            retry_async,
            with_timeout,
        )
        assert callable(with_timeout)
        assert callable(retry_async)
        assert isinstance(default_retryable(), tuple)

    def test_ratelimit_facade_lazy(self) -> None:
        from src.backend.core.facades import (
            RateLimit,
            RateLimitExceeded,
            RedisRateLimiter,
            get_rate_limiter,
        )
        assert RateLimit is not None
        assert RedisRateLimiter is not None
        assert callable(get_rate_limiter)
        assert issubclass(RateLimitExceeded, Exception)

    def test_circuit_breaker_facade_lazy(self) -> None:
        from src.backend.core.facades import ClientCircuitBreaker
        assert ClientCircuitBreaker is not None

    def test_bulkhead_facade_lazy(self) -> None:
        from src.backend.core.facades import Bulkhead, BulkheadExhausted
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


class TestFacadeRetryCanonicalImport:
    """S204 fix: verify retry canonicalization imports via facades."""

    def test_make_async_retry_via_canonical(self) -> None:
        """``make_async_retry`` directly из canonical (post-S204 fix)."""
        from src.backend.core.resilience.retry import make_async_retry
        assert callable(make_async_retry)

    def test_default_retryable_via_canonical(self) -> None:
        """``default_retryable`` directly из canonical."""
        from src.backend.core.resilience.retry import default_retryable
        types = default_retryable()
        assert ConnectionError in types
        assert OSError in types

    def test_core_facades_module_imports(self) -> None:
        """``core.facades`` импортируется без ошибок (post-S204 retry canonicalization)."""
        import src.backend.core.facades as facades_mod
        # Eager exports — ``retry_async``/``default_retryable`` теперь real symbols,
        # не lazy ``__getattr__`` mapping.
        assert callable(facades_mod.retry_async)
        assert callable(facades_mod.default_retryable)

    def test_retry_canonical_module_imports(self) -> None:
        """Canonical retry module exposes все exports без F822."""
        import src.backend.core.resilience.retry as retry_mod
        for symbol in (
            "Retry",
            "RetryPolicy",
            "RetryBudgetExhausted",
            "with_retry",
            "make_async_retry",
            "async_retry",
            "_log_before_sleep",
            "default_retryable",
            "retry_async",
        ):
            assert hasattr(retry_mod, symbol), symbol
            assert getattr(retry_mod, symbol) is not None

    def test_shims_resolve_to_canonical(self) -> None:
        """Shim modules re-export ТУ ЖЕ function object что и canonical."""
        import src.backend.core.resilience.retry as canonical
        from src.backend.core.utils import retry_helper
        from src.backend.infrastructure.resilience import retry as infra_retry

        assert retry_helper.default_retryable is canonical.default_retryable
        assert retry_helper.retry_async is canonical.retry_async
        assert infra_retry.make_async_retry is canonical.make_async_retry
        assert infra_retry.async_retry is canonical.async_retry
        assert infra_retry._log_before_sleep is canonical._log_before_sleep
