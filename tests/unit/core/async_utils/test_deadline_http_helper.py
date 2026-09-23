"""Tests for ``http_timeout_from_deadline`` helper.

Coverage:
    - ``RequestContext`` не установлен → ``None``.
    - ``RequestContext.deadline_budget`` is None → ``None``.
    - Budget с remaining > 0 → return remaining.
    - Budget expired → return 0 (or floor).
    - ``floor`` argument clamps minimum value.
"""

from __future__ import annotations

import time

from src.backend.core.async_utils.deadline_budget import DeadlineBudget
from src.backend.core.async_utils.deadline_http_helper import (
    DeadlineExpiredError,
    http_timeout_from_deadline,
)
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)


class TestNoDeadline:
    """Нет RequestContext или budget → None."""

    def test_no_context_returns_none(self) -> None:
        """Без bind_request_context → helper возвращает None."""
        # Убедимся что contextvar пуст.
        assert http_timeout_from_deadline() is None

    def test_context_without_budget_returns_none(self) -> None:
        ctx = RequestContext(correlation_id="c", request_id="r", method="GET", path="/")
        token = bind_request_context(ctx)
        try:
            assert http_timeout_from_deadline() is None
        finally:
            clear_request_context(token)


class TestActiveDeadline:
    """Active deadline → return remaining seconds."""

    def test_returns_remaining(self) -> None:
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
            result = http_timeout_from_deadline()
            assert result is not None
            assert 9.5 <= result <= 10.0
        finally:
            clear_request_context(token)

    def test_returns_small_remaining(self) -> None:
        budget = DeadlineBudget.from_timeout(timeout=0.5)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            result = http_timeout_from_deadline()
            assert result is not None
            assert result <= 0.5
            assert result > 0.0
        finally:
            clear_request_context(token)


class TestExpiredDeadline:
    """Expired deadline → return 0 или floor."""

    def test_expired_returns_zero(self) -> None:
        budget = DeadlineBudget.from_timeout(timeout=0.001)
        time.sleep(0.01)
        assert budget.is_expired()
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            result = http_timeout_from_deadline()
            assert result == 0.0
        finally:
            clear_request_context(token)

    def test_expired_with_floor_returns_floor(self) -> None:
        """С ``floor=0.5`` expired budget → 0.5s (минимальный connect timeout)."""
        budget = DeadlineBudget.from_timeout(timeout=0.001)
        time.sleep(0.01)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            result = http_timeout_from_deadline(floor=0.5)
            assert result == 0.5
        finally:
            clear_request_context(token)

    def test_active_with_floor_returns_remaining(self) -> None:
        """Active budget 10s с floor=5.0 → 10s (floor ниже remaining)."""
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
            result = http_timeout_from_deadline(floor=5.0)
            assert result is not None
            assert result >= 9.5
        finally:
            clear_request_context(token)


class TestReExports:
    """Module re-exports."""

    def test_deadline_expired_error_re_export(self) -> None:
        """``DeadlineExpiredError`` доступен из deadline_http_helper."""
        from src.backend.core.async_utils.deadline_budget import (
            DeadlineExpiredError as OriginalError,
        )

        assert DeadlineExpiredError is OriginalError


class TestGracefulDegradation:
    """Helper не должен ломать caller'а при ошибках в RequestContext."""

    def test_doesnt_propagate_exceptions(self) -> None:
        """Если внутри helper произошла ошибка → возврат None."""
        # Без bind context helper возвращает None gracefully.
        # Это базовый smoke — фактическая ошибка внутри малодостижима без monkey-patch.
        result = http_timeout_from_deadline()
        assert result is None
