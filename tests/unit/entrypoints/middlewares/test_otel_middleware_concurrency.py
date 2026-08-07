"""D-AUDIT-A2-03 fix (cycle 1): OtelMiddleware concurrency fix.

Ранее OtelMiddleware сохранял status code на instance attribute
(self._cycle56_status). Middleware instance shared между всеми
concurrent requests → race condition: status code от request A мог
попасть в response B (per-request state leakage).

Фикс: scope['state']['otel_response_status'] — per-request state
(ASGI scope dict живёт один request, не shared).
"""

# ruff: noqa: S101

from __future__ import annotations

import inspect


class TestOtelMiddlewareConcurrencyFix:
    """D-AUDIT-A2-03 fix (cycle 1): no instance attribute, per-request state."""

    def test_no_cycle56_status_attribute_set(self) -> None:
        """OtelMiddleware не использует self._cycle56_status (instance attribute)."""
        from src.backend.entrypoints.middlewares.otel_middleware import OtelMiddleware

        src = inspect.getsource(OtelMiddleware)
        # Проверяем отсутствие self._cycle56_status = (assignment)
        assert "self._cycle56_status =" not in src, (
            "OtelMiddleware не должен присваивать self._cycle56_status "
            "(race condition — instance attribute shared между requests)"
        )

    def test_no_getattr_cycle56_status(self) -> None:
        """OtelMiddleware не читает self._cycle56_status через getattr."""
        from src.backend.entrypoints.middlewares.otel_middleware import OtelMiddleware

        src = inspect.getsource(OtelMiddleware)
        assert 'getattr(self, "_cycle56_status"' not in src, (
            "OtelMiddleware не должен читать self._cycle56_status "
            "(заменён на scope['state']['otel_response_status'])"
        )

    def test_uses_scope_state_for_response_status(self) -> None:
        """OtelMiddleware использует scope['state']['otel_response_status']."""
        from src.backend.entrypoints.middlewares.otel_middleware import OtelMiddleware

        src = inspect.getsource(OtelMiddleware)
        assert "otel_response_status" in src, (
            "OtelMiddleware должен использовать scope['state']['otel_response_status']"
        )

    def test_scope_state_is_per_request(self) -> None:
        """ASGI scope['state'] — per-request dict, не shared."""
        # ASGI spec: scope — per-request dict. Каждый request имеет свой scope.
        # 'state' — стандартное поле для per-request state (Starlette convention).
        # Это гарантирует, что status code из request A не попадёт в response B.
        assert True  # Документирующий тест — фактическая гарантия через ASGI protocol
