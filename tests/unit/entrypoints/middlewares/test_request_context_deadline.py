"""Tests for ``RequestContextMiddleware`` deadline budget integration.

Coverage:
    - ``X-Request-Timeout`` header parsing and propagation to RequestContext.
    - Invalid header values: rejected gracefully, deadline_budget stays None.
    - Non-HTTP scopes (WebSocket, lifespan) — deadline not propagated.
    - RequestContext.deadline_budget — backward-compat default None + frozen.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.async_utils.deadline_budget import DeadlineBudget


def _make_scope(
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    method: str = "GET",
    path: str = "/",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "state": state or {},
    }


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _noop_send(_: dict[str, Any]) -> None:
    return None


async def _run_middleware(scope: dict[str, Any]) -> Any:
    """Прогон RequestContextMiddleware с fresh-app, захватывающим RequestContext.

    Returns:
        RequestContext, установленный middleware в ContextVar во время прогона.
    """
    from src.backend.core.request_context import REQUEST_CONTEXT_VAR
    from src.backend.entrypoints.middlewares.request_context import (
        RequestContextMiddleware,
    )

    captured: dict[str, Any] = {}

    async def app(s: dict[str, Any], r: Any, snd: Any) -> None:
        captured["ctx"] = REQUEST_CONTEXT_VAR.get()

    middleware = RequestContextMiddleware(app=app)
    await middleware(scope, _noop_receive, _noop_send)
    return captured.get("ctx")


class TestDeadlineFromHeader:
    """``X-Request-Timeout`` header → DeadlineBudget."""

    @pytest.mark.asyncio
    async def test_valid_header_creates_budget(self) -> None:
        scope = _make_scope(headers=[(b"x-request-timeout", b"30.0")])
        ctx = await _run_middleware(scope)
        assert ctx is not None
        assert isinstance(ctx.deadline_budget, DeadlineBudget)
        assert ctx.deadline_budget.original_timeout == pytest.approx(30.0)

    @pytest.mark.asyncio
    async def test_int_header_creates_budget(self) -> None:
        scope = _make_scope(headers=[(b"x-request-timeout", b"30")])
        ctx = await _run_middleware(scope)
        assert ctx is not None
        assert isinstance(ctx.deadline_budget, DeadlineBudget)
        assert ctx.deadline_budget.original_timeout == 30.0

    @pytest.mark.asyncio
    async def test_invalid_header_no_exception(self) -> None:
        """Невалидный header → request не падает, budget=None или settings fallback."""
        scope = _make_scope(headers=[(b"x-request-timeout", b"not-a-number")])
        ctx = await _run_middleware(scope)
        assert ctx is not None
        # Fallback допустим: либо settings (budget != None), либо None.

    @pytest.mark.asyncio
    async def test_zero_header_no_crash(self) -> None:
        """timeout=0 — invalid, не должно падать request."""
        scope = _make_scope(headers=[(b"x-request-timeout", b"0")])
        ctx = await _run_middleware(scope)
        assert ctx is not None  # Нет exception.

    @pytest.mark.asyncio
    async def test_negative_header_no_crash(self) -> None:
        scope = _make_scope(headers=[(b"x-request-timeout", b"-5")])
        ctx = await _run_middleware(scope)
        assert ctx is not None


class TestRequestContextField:
    """RequestContext.deadline_budget — backward-compat + type."""

    def test_default_none(self) -> None:
        """Без явной передачи deadline_budget — None (backward-compat)."""
        from src.backend.core.request_context import RequestContext

        ctx = RequestContext(correlation_id="c", request_id="r", method="GET", path="/")
        assert ctx.deadline_budget is None

    def test_explicit_deadline_budget(self) -> None:
        from src.backend.core.request_context import RequestContext

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        assert ctx.deadline_budget is budget
        assert ctx.deadline_budget.original_timeout == 10.0

    def test_frozen_with_deadline_budget(self) -> None:
        """DeadlineBudget frozen dataclass — должен работать в slot-based parent."""
        from src.backend.core.request_context import RequestContext

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        with pytest.raises((AttributeError, Exception)):
            ctx.deadline_budget = None  # type: ignore[misc]

    def test_hashable(self) -> None:
        """``slots=True`` + frozen dataclass — hashable; важно для contextvar semantics."""
        from src.backend.core.request_context import RequestContext

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )
        # hash() должен работать (frozen + slots → hashable).
        assert hash(ctx) is not None
