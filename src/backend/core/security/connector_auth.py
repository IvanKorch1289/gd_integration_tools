"""Connector authorization decorator (Security Wave S2).

Универсальный auth-decorator для connector-операций (Sinks / Sources / RPA / MCP).
Декорирует методы ``Sink.send``, ``Source.verify_and_dispatch``,
``Source.stream``, ``RPA.process_step`` и т.п. Делает capability check через
:class:`AuthorizationFacade` (S183+S186 unified facade).

Паттерн: обёртка вызывает ``facade.check_principal()`` перед вызовом метода.
При отсутствии facade (test/dev_light) — fail-closed (deny + log WARNING).

Usage::

    class KafkaSink(Sink):
        @require_capability("kafka.write", action="write")
        async def send(self, payload: dict) -> SinkResult:
            ...

    # Передача principal в runtime:
    await sink.send(payload, _principal="user-123", _ctx={"topic": "orders"})

Sprint 172, Wave S2 (connector authorization extension).
"""

from __future__ import annotations

from functools import wraps
from typing import Any, ParamSpec, TypeVar

from src.backend.core.logging import get_logger

__all__ = (
    "ConnectorAuthError",
    "check_source_capability",
    "require_capability",
)


class ConnectorAuthError(PermissionError):
    """Raised when capability check fails for a connector operation."""


_P = ParamSpec("_P")
_R = TypeVar("_R")

_logger = get_logger("core.security.connector_auth")


def require_capability(
    capability: str,
    *,
    action: str = "execute",
    scope: str = "tenant",
) -> Any:
    """Decorator factory: auth-check перед вызовом метода connector'а.

    Args:
        capability: Имя требуемой capability (``kafka.write`` / ``rpa.execute``).
        action: Действие (``read`` / ``write`` / ``execute``).
        scope: Scope проверки. Сейчас используется только ``"tenant"`` —
            берётся tenant_id из текущего ``TenantContext``. ``"global"`` /
            ``"principal"`` зарезервированы для будущего расширения.

    Returns:
        Decorator, оборачивающий ``async def`` метод.

    Raises:
        ConnectorAuthError: Если capability check failed (fail-closed).

    """
    if not capability or not isinstance(capability, str):
        raise ValueError("capability must be non-empty string")

    def decorator(func: Any) -> Any:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Lazy import — избежать циклических зависимостей (auth → core).
            try:
                from src.backend.services.authorization.facade import (
                    get_authorization_facade,
                )
            except Exception as exc:  # pragma: no cover — facade недоступен в test
                _logger.debug(
                    "authorization_facade_unavailable: %s; failing closed",
                    exc,
                )
                raise ConnectorAuthError(
                    f"Capability '{capability}' denied: facade unavailable",
                ) from exc

            principal = kwargs.pop("_principal", "anonymous")
            extra_ctx = kwargs.pop("_ctx", None) or {}

            # Resolve tenant_id из TenantContext (если есть).
            tenant_id: str | None = None
            if scope == "tenant":
                try:
                    from src.backend.core.tenancy import (
                        current_tenant,  # noqa: F401 — availability probe
                    )

                    ctx = current_tenant()
                    if ctx is not None:
                        tenant_id = ctx.tenant_id
                except (ImportError, AttributeError, RuntimeError) as ten_exc:  # pragma: no cover
                    # cycle-9/D-AUDIT-1037: narrow exceptions + observability.
                    # ImportError — tenancy missing, AttributeError — context
                    # API change, RuntimeError — context unavailable.
                    import logging  # noqa: F401 — availability probe
                    logging.getLogger(__name__).debug(
                        "connector_auth.current_tenant_fallback",
                        extra={"error": str(ten_exc)},
                    )
                    tenant_id = None

            facade = get_authorization_facade()
            try:
                decision = await facade.check_principal(
                    principal=principal,
                    required_action=action,
                    required_resource=capability,
                    context={"tenant_id": tenant_id, **extra_ctx},
                )
            except Exception as exc:
                # Fail-closed: если facade выбросил исключение, deny.
                _logger.warning(
                    "connector_auth_check_error: capability=%s action=%s "
                    "principal=%s error=%s",
                    capability,
                    action,
                    principal,
                    exc,
                )
                raise ConnectorAuthError(
                    f"Capability '{capability}' denied: facade error: {exc}",
                ) from exc

            if not decision.allowed:
                _logger.warning(
                    "connector_capability_denied: capability=%s action=%s "
                    "principal=%s tenant=%s reason=%s",
                    capability,
                    action,
                    principal,
                    tenant_id,
                    decision.reason,
                )
                raise ConnectorAuthError(
                    f"Capability '{capability}' denied for {principal}: "
                    f"{decision.reason or 'policy denied'}",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


async def check_source_capability(
    capability: str,
    *,
    action: str = "read",
    principal: str = "anonymous",
    extra_ctx: dict[str, Any] | None = None,
) -> bool:
    """Проверяет capability для source-операции (stream / verify_and_dispatch).

    Отличие от :func:`require_capability`: возвращает ``bool`` вместо
    raise. Используется в местах, где raising ломает long-lived
    stream-генератор (например, внутри ``async def stream()`` — auth
    делается один раз в начале сессии, а не на каждое событие).

    Args:
        capability: Имя требуемой capability (``kafka.read`` / ``http.read``).
        action: Действие (``read`` / ``execute``).
        principal: Caller identity (по умолчанию ``"anonymous"``).
        extra_ctx: Дополнительный контекст для auth (source_id, topic, ...).

    Returns:
        ``True`` если доступ разрешён, ``False`` иначе.

    Note:
        При недоступности AuthorizationFacade — fail-closed (returns False).

    """
    try:
        from src.backend.services.authorization.facade import get_authorization_facade
    except Exception as exc:  # pragma: no cover
        _logger.debug(
            "authorization_facade_unavailable: %s; failing closed", exc,
        )
        return False

    tenant_id: str | None = None
    try:
        from src.backend.core.tenancy import (
            current_tenant,  # noqa: F401 — availability probe
        )

        ctx = current_tenant()
        if ctx is not None:
            tenant_id = ctx.tenant_id
    except (ImportError, AttributeError, RuntimeError) as ten_exc:  # pragma: no cover
        # cycle-9/D-AUDIT-1078: narrow exceptions + observability.
        # ImportError — tenancy missing, AttributeError — context API
        # change, RuntimeError — context unavailable.
        import logging  # noqa: F401 — availability probe
        logging.getLogger(__name__).debug(
            "connector_auth.tenant_id_fallback",
            extra={"error": str(ten_exc)},
        )
        tenant_id = None

    facade = get_authorization_facade()
    try:
        decision = await facade.check_principal(
            principal=principal,
            required_action=action,
            required_resource=capability,
            context={"tenant_id": tenant_id, **(extra_ctx or {})},
        )
    except Exception as exc:
        _logger.warning(
            "source_auth_check_error: capability=%s action=%s principal=%s error=%s",
            capability,
            action,
            principal,
            exc,
        )
        return False

    if not decision.allowed:
        _logger.warning(
            "source_capability_denied: capability=%s action=%s principal=%s "
            "tenant=%s reason=%s",
            capability,
            action,
            principal,
            tenant_id,
            decision.reason,
        )
    return decision.allowed
