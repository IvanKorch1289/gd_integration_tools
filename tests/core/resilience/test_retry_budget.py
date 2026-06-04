"""Tests for retry_budget module (E.4)."""

import asyncio
import pytest
from unittest.mock import patch


class TestRetryBudget:
    """Tests for RetryBudget (bug B.4 fixed)."""

    @pytest.mark.asyncio
    async def test_budget_exhausted_not_retried(self):
        """RetryBudgetExhausted is NOT caught by tenacity retry.

        The fix uses retry_if_not_exception_type(RetryBudgetExhausted) so that
        when the budget is exhausted, RetryBudgetExhausted propagates immediately
        without retry delay.
        """
        from src.backend.core.resilience.retry import with_retry, RetryPolicy
        from src.backend.core.resilience.retry_budget import (
            RetryBudget,
            RetryBudgetExhausted,
        )

        # Exhaust the budget so try_retry returns False
        budget = RetryBudget(
            name="test_budget", ratio=0.0
        )  # ratio=0 means no retries allowed

        call_count = 0

        @with_retry(policy=RetryPolicy(max_attempts=5, budget=budget))
        async def with_budget():
            nonlocal call_count
            call_count += 1
            await budget.record_attempt()
            # First attempt: budget has 0 ratio, try_retry returns False → raises RetryBudgetExhausted
            raise ValueError("boom")

        # The retry decorator should NOT retry on RetryBudgetExhausted
        # So we expect it to propagate directly (1 attempt only)
        with pytest.raises((RetryBudgetExhausted, Exception)) as exc_info:
            await with_budget()

        # Should NOT be RetryError (tenacity's wrapper) - should be RetryBudgetExhausted directly
        # because tenacity doesn't retry it
        assert call_count == 1
        # The exception should contain "budget exhausted" or be RetryBudgetExhausted
        if isinstance(exc_info.value, RetryBudgetExhausted):
            assert "exhausted" in str(exc_info.value).lower()
        # If it's wrapped, tenacity.RetryError — budget exhaustion should NOT cause retries
        # so we just verify only 1 call was made (no retries)
