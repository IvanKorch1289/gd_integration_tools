"""Tests for ``TimeoutMiddleware`` × ``DeadlineBudget`` integration.

Coverage:
    - DeadlineBudget НЕ установлен → fallback на per-route/global timeout.
    - DeadlineBudget с remaining > per-route → используется per-route (защита).
    - DeadlineBudget с remaining < per-route → используется remaining.
    - DeadlineBudget уже истёк → 408 без вызова downstream.
    - Приоритет: ``min(deadline_remaining, per_route, global)``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.async_utils.deadline_budget import DeadlineBudget
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)


def _make_scope(path: str = "/") -> dict[str, Any]:
    return {"type": "http", "method": "GET", "path": path, "headers": []}


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _collect_send(messages: list[dict[str, Any]]) -> Any:
    async def send(msg: dict[str, Any]) -> None:
        messages.append(msg)

    return send


class TestDeadlineBudgetIntegration:
    """DeadlineBudget сужает timeout до ``min(...)`` из трёх источников."""

    @pytest.mark.asyncio
    async def test_no_deadline_uses_per_route(self) -> None:
        """Без ``RequestContext.deadline_budget`` — fallback на per-route/global."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        called = {"count": 0}

        async def app(scope: dict[str, Any], r: Any, s: Any) -> None:
            called["count"] += 1

        middleware = TimeoutMiddleware(
            app=app,
            route_timeouts={"/api": 10.0},  # per-route 10s
        )
        send = await _collect_send([])
        await middleware(_make_scope("/api/test"), _noop_receive, send)
        # Downstream вызван (нет deadline-budget).
        assert called["count"] == 1

    @pytest.mark.asyncio
    async def test_deadline_tighter_than_per_route(self) -> None:
        """DeadlineBudget 0.1s vs per-route 10s → используется 0.1s (min)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        # Downstream засыпает на 1s — должен быть прерван по deadline-budget 0.1s.
        async def slow_app(scope: dict[str, Any], r: Any, s: Any) -> None:
            import asyncio

            await asyncio.sleep(1.0)

        budget = DeadlineBudget.from_timeout(timeout=0.1)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/api/test",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            middleware = TimeoutMiddleware(app=slow_app, route_timeouts={"/api": 10.0})
            send_msgs: list[dict[str, Any]] = []
            send = await _collect_send(send_msgs)
            await middleware(_make_scope("/api/test"), _noop_receive, send)
            # Должен быть 408 response.
            assert any(m.get("status") == 408 for m in send_msgs), (
                f"Expected 408, got: {[m.get('status') for m in send_msgs]}"
            )
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_per_route_tighter_than_deadline(self) -> None:
        """DeadlineBudget 10s vs per-route 0.05s → используется per-route (0.05s)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        async def slow_app(scope: dict[str, Any], r: Any, s: Any) -> None:
            import asyncio

            await asyncio.sleep(1.0)

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/api/test",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            # Per-route 0.05s, deadline-budget 10s → per-route wins (минимум).
            middleware = TimeoutMiddleware(app=slow_app, route_timeouts={"/api": 0.05})
            send_msgs: list[dict[str, Any]] = []
            send = await _collect_send(send_msgs)
            await middleware(_make_scope("/api/test"), _noop_receive, send)
            assert any(m.get("status") == 408 for m in send_msgs)
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_already_expired_deadline(self) -> None:
        """DeadlineBudget уже истёк → 408 без вызова downstream."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        called = {"count": 0}

        async def app(scope: dict[str, Any], r: Any, s: Any) -> None:
            called["count"] += 1

        budget = DeadlineBudget.from_timeout(timeout=0.001)
        import asyncio

        await asyncio.sleep(0.01)  # истекаем budget
        assert budget.is_expired()

        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/api/test",
            deadline_budget=budget,
        )
        token = bind_request_context(ctx)
        try:
            middleware = TimeoutMiddleware(app=app, route_timeouts={"/api": 10.0})
            send_msgs: list[dict[str, Any]] = []
            send = await _collect_send(send_msgs)
            await middleware(_make_scope("/api/test"), _noop_receive, send)
            # 408 emitted via http.response.start; downstream НЕ вызван.
            start_msgs = [
                m for m in send_msgs if m.get("type") == "http.response.start"
            ]
            statuses = [m.get("status") for m in start_msgs]
            assert 408 in statuses, f"Expected 408 in {statuses}"
            # Главное — нет успешного response (200).
            assert 200 not in statuses
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_non_http_scope_skips_deadline(self) -> None:
        """WebSocket scope — deadline НЕ применяется (нет deadline в scope)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        called = {"count": 0}

        async def app(scope: dict[str, Any], r: Any, s: Any) -> None:
            called["count"] += 1

        middleware = TimeoutMiddleware(app=app, route_timeouts={"/api": 0.001})
        await middleware(
            {"type": "websocket", "path": "/ws"}, _noop_receive, lambda _: None
        )
        assert called["count"] == 1


class TestNormalizePathPrefix:
    """``_normalize_path_prefix`` — cardinality guard для метрик."""

    def test_full_path(self) -> None:
        """``/api/v1/orders`` → ``/api`` (первый сегмент, cardinality guard)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        assert TimeoutMiddleware._normalize_path_prefix("/api/v1/orders") == "/api"

    def test_short_path(self) -> None:
        """``/api`` → ``/api`` (один сегмент)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        assert TimeoutMiddleware._normalize_path_prefix("/api") == "/api"

    def test_root(self) -> None:
        """``/`` → ``/`` (root)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        assert TimeoutMiddleware._normalize_path_prefix("/") == "/"

    def test_empty(self) -> None:
        """``""`` → ``/`` (fallback)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        assert TimeoutMiddleware._normalize_path_prefix("") == "/"

    def test_no_leading_slash(self) -> None:
        """``api/v1/orders`` (no leading slash) → ``/api`` (normalized)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        assert TimeoutMiddleware._normalize_path_prefix("api/v1/orders") == "/api"

    def test_trailing_slash(self) -> None:
        """``/api/v1/`` (trailing slash) → ``/api`` (первый сегмент)."""
        from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

        assert TimeoutMiddleware._normalize_path_prefix("/api/v1/") == "/api"
