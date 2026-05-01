"""Хелперы построения :class:`DispatchContext` для entrypoint-адаптеров (W14.1.D).

Каждый transport (HTTP/WS/Scheduler/...) собирает свой ``DispatchContext``
с обязательным ``correlation_id``: если он не передан вызывающей стороной
(например, нет ``X-Correlation-Id`` header'а), генерируется новый UUID4.

Хелпер централизует генерацию ID и source-маркировку, чтобы entrypoints
не дублировали одну и ту же логику и чтобы ``correlation_id`` всегда был
заполнен (это важно для AuditMiddleware и distributed tracing).
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from src.core.interfaces.action_dispatcher import DispatchContext

__all__ = ("make_dispatch_context",)


def make_dispatch_context(
    source: str,
    *,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    idempotency_key: str | None = None,
    trace_parent: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> DispatchContext:
    """Создаёт :class:`DispatchContext` с гарантированным ``correlation_id``.

    Args:
        source: Имя транспорта-источника (``"http"``, ``"ws"``,
            ``"scheduler"``, ``"grpc"``, ...).
        correlation_id: Сквозной ID запроса. Если ``None`` — генерируется
            новый UUID4 (hex-форма без дефисов).
        tenant_id: Идентификатор арендатора (мультиарендность).
        user_id: Идентификатор пользователя-инициатора.
        idempotency_key: Ключ идемпотентности (если есть в запросе).
        trace_parent: W3C ``traceparent`` header value.
        attributes: Произвольные атрибуты транспорта (request_path,
            client_ip, и т.п.).

    Returns:
        Заполненный :class:`DispatchContext`.
    """
    return DispatchContext(
        correlation_id=correlation_id or uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
        source=source,
        trace_parent=trace_parent,
        attributes=dict(attributes) if attributes else {},
    )
