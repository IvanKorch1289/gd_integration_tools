"""Edge-case tests for ``http_timeout_from_deadline`` graceful degradation.

Coverage:
    - ``deadline_budget`` имеет неожиданный type → ``None`` (graceful).
    - ``deadline_budget.remaining()`` raises → ``None`` (graceful).
    - Параметр ``floor > remaining`` → возвращается ``remaining`` (max).
"""

from __future__ import annotations

from src.backend.core.async_utils.deadline_budget import DeadlineBudget
from src.backend.core.async_utils.deadline_http_helper import http_timeout_from_deadline
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)


class TestGracefulDegradation:
    """Helper должен быть устойчив к malformed RequestContext / deadline_budget."""

    def test_deadline_budget_with_broken_remaining_returns_none(self) -> None:
        """Если ``remaining()`` raises → graceful None."""

        class _BrokenBudget:
            def remaining(self) -> float:
                raise RuntimeError("simulated failure")

        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=_BrokenBudget(),  # type: ignore[arg-type]
        )
        token = bind_request_context(ctx)
        try:
            result = http_timeout_from_deadline()
            assert result is None
        finally:
            clear_request_context(token)

    def test_deadline_budget_with_missing_remaining_returns_none(self) -> None:
        """Если ``remaining`` attribute отсутствует → graceful None."""

        class _IncompleteBudget:
            pass  # No remaining()

        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=_IncompleteBudget(),  # type: ignore[arg-type]
        )
        token = bind_request_context(ctx)
        try:
            result = http_timeout_from_deadline()
            assert result is None
        finally:
            clear_request_context(token)


class TestFloorEdgeCases:
    """Floor param clamping."""

    def test_floor_below_remaining_returns_remaining(self) -> None:
        """``floor=1.0`` при remaining=10.0 → return 10.0 (max wins)."""
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            result = http_timeout_from_deadline(floor=1.0)
            assert result is not None
            assert result >= 9.5
        finally:
            clear_request_context(token)

    def test_negative_floor_returns_remaining(self) -> None:
        """Negative floor → max(negative, remaining) = remaining."""
        budget = DeadlineBudget.from_timeout(timeout=5.0)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            result = http_timeout_from_deadline(floor=-1.0)
            assert result is not None
            assert result >= 4.5
        finally:
            clear_request_context(token)


class TestReExportErrorClass:
    """``DeadlineExpiredError`` re-exported for convenience."""

    def test_re_exported_class_is_original(self) -> None:
        from src.backend.core.async_utils.deadline_budget import (
            DeadlineExpiredError as Original,
        )
        from src.backend.core.async_utils.deadline_http_helper import (
            DeadlineExpiredError as Re,
        )

        assert Re is Original
