"""Tests for @policy decorator (E.2)."""

import pytest


class TestPolicyDecorator:
    """Tests for composite @policy decorator."""

    @pytest.mark.asyncio
    async def test_policy_with_breaker_spec(self):
        """@policy(circuit_breaker=BreakerSpec(name='test', failure_threshold=3))."""
        from src.backend.core.resilience.breaker import BreakerSpec
        from src.backend.core.resilience.decorators import policy

        @policy(circuit_breaker=BreakerSpec(name="test_spec", failure_threshold=3))
        async def dummy():
            return "ok"

        # Should not raise - BreakerSpec is accepted
        result = await dummy()
        assert result == "ok"

        # Cleanup registry
        from src.backend.core.resilience.breaker import get_breaker_registry

        reg = get_breaker_registry()
        if "test_spec" in reg._breakers:
            del reg._breakers["test_spec"]

    @pytest.mark.asyncio
    async def test_policy_with_breaker_name(self):
        """@policy(circuit_breaker='my_breaker') resolves by name."""
        from src.backend.core.resilience.decorators import policy

        @policy(circuit_breaker="my_breaker_name")
        async def dummy2():
            return "ok"

        result = await dummy2()
        assert result == "ok"

        # Cleanup
        from src.backend.core.resilience.breaker import get_breaker_registry

        reg = get_breaker_registry()
        if "my_breaker_name" in reg._breakers:
            del reg._breakers["my_breaker_name"]

    @pytest.mark.asyncio
    async def test_policy_with_retry(self):
        """@policy(retry=RetryPolicy(max_attempts=3)) retries on failure."""
        from src.backend.core.resilience.decorators import policy
        from src.backend.core.resilience.retry import RetryPolicy

        call_count = 0

        @policy(retry=RetryPolicy(max_attempts=3))
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not ready")
            return "success"

        result = await flaky()
        assert result == "success"
        assert call_count == 3
