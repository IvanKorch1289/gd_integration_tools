"""ADR-NEW-3 (Sprint 17): :class:`RequestContextMiddleware` — pure ASGI.

Назначение:
    Один раз, в начале обработки запроса, собирает поля
    (``correlation_id`` / ``request_id`` / ``tenant_id`` / OTel
    ``trace_id``+``span_id`` / HTTP ``method``+``path``) и устанавливает
    :class:`RequestContext` через :func:`bind_request_context`.

    Backward-compat: дополнительно пишет ``correlation_id`` в
    ``scope["state"]`` — позволяет существующим callsites через
    ``request.state.correlation_id`` продолжать работать (deprecated).

Размещение в цепочке:
    Регистрируется в ``setup_middlewares`` после ``TenantMiddleware``
    (см. `setup_middlewares.py`). Это значит ContextVar обновляется
    рано в pipeline (после распарсивания correlation/tenant headers).

Источники полей:
    1. ``X-Correlation-ID`` header (или генерация uuid4 при отсутствии);
    2. ``X-Request-ID`` header (или генерация uuid4);
    3. ``X-Tenant-ID`` header;
    4. OTel ``trace.get_current_span()`` через ``trace_id`` / ``span_id``;
    5. ``scope["state"]["auth"]`` (если установлен upstream MW).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.backend.core.request_context import (  # noqa: F401 — re-export
    RequestContext,
    bind_request_context,
    clear_request_context,
)

logger = logging.getLogger(__name__)

__all__ = ("RequestContextMiddleware",)


def _get_header(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    """Получить значение заголовка (case-insensitive) или None."""
    target = name.lower()
    for key, value in headers:
        if key.lower() == target:
            return value.decode("latin-1")
    return None


def _otel_ids() -> tuple[str | None, str | None]:
    """Извлечь ``trace_id`` / ``span_id`` из активного OTel span."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context() if span is not None else None
        if ctx is None or not ctx.is_valid:
            return None, None
        # OTel id формат — int → hex без префикса
        return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    except Exception as _:
        return None, None


def _resolve_deadline_timeout() -> float | None:
    """Извлечь default timeout из settings для HTTP-requests.

    Returns:
        Timeout в секундах или None, если settings недоступны.
    """
    try:
        from src.backend.core.config.settings import settings

        secure = getattr(settings, "secure", None)
        if secure is None:
            return None
        # ``request_timeout`` — наиболее вероятное поле (S18 W6 TimeoutMiddleware
        # использует то же имя). Fallback для гипотетических альтернатив.
        for attr in ("request_timeout", "default_request_timeout"):
            value = getattr(secure, attr, None)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
    except Exception:
        # На старте (без конфигурации) — никакого default deadline.
        pass
    return None


def _parse_deadline_header(value: str) -> float | None:
    """Парсинг ``X-Request-Timeout`` header (секунды, float).

    Возвращает ``None`` если header отсутствует, не парсится или
    неположительный. Логирует WARNING для подозрительных значений —
    помогает выявлять клиентов с некорректным timeout.

    Args:
        value: строковое значение header.

    Returns:
        Timeout в секундах или None.
    """
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        logger.warning("X-Request-Timeout not parseable: %r", value)
        return None
    if timeout <= 0 or timeout != timeout:  # reject 0/negative/NaN
        logger.warning("X-Request-Timeout non-positive or NaN: %r", value)
        return None
    return timeout


class RequestContextMiddleware:
    """Pure ASGI middleware: собирает и публикует :class:`RequestContext`."""

    def __init__(self, app: Any) -> None:
        """Инициализирует middleware.

        :param app: значение app.
        """
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", []) or []
        correlation_id = _get_header(headers, b"x-correlation-id") or str(uuid.uuid4())
        request_id = _get_header(headers, b"x-request-id") or str(uuid.uuid4())
        tenant_id = _get_header(headers, b"x-tenant-id")
        trace_id, span_id = _otel_ids()
        state = scope.setdefault("state", {})
        auth_value = state.get("auth") if isinstance(state, dict) else None
        auth: dict[str, Any] | None = None
        if isinstance(auth_value, dict):
            auth = dict(auth_value)
        client_id = None
        if isinstance(state, dict):
            raw_client_id = state.get("client_id")
            if isinstance(raw_client_id, str):
                client_id = raw_client_id

        # ADR-0305: deadline propagation. Priority:
        # 1. ``X-Request-Timeout`` header (per-request override).
        # 2. ``settings.secure.request_timeout`` (default).
        # 3. ``None`` (legacy / non-configured — no deadline propagation).
        deadline_budget: Any = None
        try:
            from src.backend.core.async_utils.deadline_budget import DeadlineBudget

            header_value = _get_header(headers, b"x-request-timeout")
            timeout_s: float | None = (
                _parse_deadline_header(header_value)
                if header_value is not None
                else None
            )
            if timeout_s is None:
                timeout_s = _resolve_deadline_timeout()
            if timeout_s is not None:
                deadline_budget = DeadlineBudget.from_timeout(timeout=timeout_s)
        except Exception as _:
            # Если DeadlineBudget/timeout parsing/import упал — продолжаем
            # без deadline (graceful degradation, не ломаем request).
            deadline_budget = None

        ctx = RequestContext(
            correlation_id=correlation_id,
            request_id=request_id,
            method=str(scope.get("method", "")),
            path=str(scope.get("path", "")),
            trace_id=trace_id,
            span_id=span_id,
            tenant_id=tenant_id,
            auth=auth,
            client_id=client_id,
            deadline_budget=deadline_budget,
        )

        # Backward-compat: scope["state"]["correlation_id"] (deprecated).
        if isinstance(state, dict):
            state.setdefault("correlation_id", correlation_id)
            state.setdefault("request_context", ctx)

        token = bind_request_context(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            clear_request_context(token)
