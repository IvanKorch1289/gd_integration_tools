"""Tests for Cycle 36 TokenBudget fail-closed feature_flag override.

Validates:
- Default behavior (flag OFF): fail-open on backend errors (preserved)
- Flag enabled: raises BudgetBackendUnavailable (new)
- Per-tenant fail_mode='closed' still works (unchanged)
- Flag-enabled takes precedence over per-tenant fail_mode='open'
"""

from __future__ import annotations

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.tenancy.token_budget import (
    BudgetBackendUnavailable,
    BudgetPeriod,
    InMemoryTokenBudgetBackend,
    TokenBudget,
    TokenBudgetConfig,
)


def _budget_with_fail_mode(fail_mode: str) -> TokenBudget:
    """Helper: build TokenBudget with explicit per-tenant fail_mode."""
    backend = InMemoryTokenBudgetBackend()
    return TokenBudget(
        backend=backend,
        default_config=TokenBudgetConfig(
            soft_limit=100,
            hard_limit=200,
            period=BudgetPeriod.DAILY,
            fail_mode=fail_mode,
        ),
    )


class _FailingBackend(InMemoryTokenBudgetBackend):
    """Backend whose increment() always raises (simulates Redis outage)."""

    async def increment(self, key: str, amount: int, ttl_seconds: int) -> int:
        raise ConnectionError("redis down")


class TestTokenBudgetFailMode:
    """Existing fail_mode behavior (unchanged)."""

    @pytest.mark.asyncio
    async def test_fail_open_default_does_not_raise(self) -> None:
        """fail_mode='open' (default): backend error is swallowed."""
        budget = _budget_with_fail_mode("open")
        budget._backend = _FailingBackend()  # type: ignore[assignment]
        snapshot = await budget.reserve(tenant_id="t1", tokens=10)
        # Snapshot returned with used=0 (no enforcement due to error)
        assert snapshot.used == 0

    @pytest.mark.asyncio
    async def test_fail_closed_raises(self) -> None:
        """fail_mode='closed': backend error propagates as BudgetBackendUnavailable."""
        budget = _budget_with_fail_mode("closed")
        budget._backend = _FailingBackend()  # type: ignore[assignment]
        with pytest.raises(BudgetBackendUnavailable) as exc_info:
            await budget.reserve(tenant_id="t1", tokens=10)
        assert exc_info.value.tenant_id == "t1"
        assert exc_info.value.backend == "token_budget"


class TestTokenBudgetFeatureFlagOverride:
    """Cycle 36: feature_flags.token_budget_fail_closed overrides per-tenant config."""

    @pytest.mark.asyncio
    async def test_flag_off_preserves_per_tenant_fail_open(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """flag=False: per-tenant fail_mode='open' still swallows errors."""
        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", False)
        budget = _budget_with_fail_mode("open")
        budget._backend = _FailingBackend()  # type: ignore[assignment]
        snapshot = await budget.reserve(tenant_id="t1", tokens=10)
        assert snapshot.used == 0  # no raise, fail-open preserved

    @pytest.mark.asyncio
    async def test_flag_on_overrides_fail_open_to_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """flag=True overrides per-tenant fail_mode='open' → raises BudgetBackendUnavailable.

        Critical for production safety: even misconfigured per-tenant configs
        fail closed when the global flag is on.
        """
        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", True)
        budget = _budget_with_fail_mode("open")  # per-tenant says open
        budget._backend = _FailingBackend()  # type: ignore[assignment]
        with pytest.raises(BudgetBackendUnavailable):
            await budget.reserve(tenant_id="t1", tokens=10)

    @pytest.mark.asyncio
    async def test_flag_on_idempotent_with_explicit_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """flag=True + per-tenant fail_mode='closed' → still raises (no double-raise)."""
        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", True)
        budget = _budget_with_fail_mode("closed")
        budget._backend = _FailingBackend()  # type: ignore[assignment]
        with pytest.raises(BudgetBackendUnavailable):
            await budget.reserve(tenant_id="t1", tokens=10)

    @pytest.mark.asyncio
    async def test_flag_on_does_not_break_happy_path(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """flag=True with working backend: no raise, normal budget tracking."""
        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", True)
        budget = _budget_with_fail_mode("open")
        # Don't override backend — use working InMemoryTokenBudgetBackend.
        snapshot = await budget.reserve(tenant_id="t1", tokens=10)
        assert snapshot.used == 10
        assert snapshot.hard_limit == 200

    def test_feature_flag_field_exists(self) -> None:
        """Verify feature_flags has token_budget_fail_closed field."""
        assert hasattr(feature_flags, "token_budget_fail_closed")
        assert feature_flags.token_budget_fail_closed is False  # default OFF
