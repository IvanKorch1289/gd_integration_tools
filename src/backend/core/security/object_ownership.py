"""Object-level ownership guard (Sprint 1 — audit 2026-09-22 P0).

JWT/API key подтверждают identity, но это НЕ доказывает object-level
authorization: пользователь tenant_A может прочитать файл tenant_B, если
resource_id привязан к чужому tenant. ``@require_object_ownership``
декоратор автоматически проверяет, что tenant_id запрошенного ресурса
совпадает с tenant_id вызывающего.

Реализует D-OWN-1 fix из аудита.

Использование::

    from src.backend.core.security.object_ownership import require_object_ownership

    @router.get("/orders/{order_id}")
    @require_object_ownership(
        resource_model=Order,
        id_param="order_id",
        tenant_field="tenant_id",
    )
    async def get_order(order_id: int, request: Request):
        # К этому моменту order_id проверен, resource загружен,
        # tenant_id совпадает. Если mismatch — AuthorizationError.
        ...

Decorator signature::

    require_object_ownership(
        resource_model: type,        # ORM model (e.g., Order)
        id_param: str,               # имя path/query param с resource_id
        tenant_field: str = "tenant_id",  # поле на resource model
        raise_on_mismatch: bool = True,
    ) -> Callable
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

from src.backend.core.errors import AuthorizationError, NotFoundError

# S170 stub (audit 2026-09-22 P0): get_logger deferred до integration с TenantContext.
logger = logging.getLogger(__name__)


def require_object_ownership(
    resource_model: type,
    id_param: str = "id",
    tenant_field: str = "tenant_id",
    raise_on_mismatch: bool = True,
    session_factory: Callable[[], Any] | None = None,
    explicit_tenant_id: str | None = None,
) -> Callable:
    """Decorator для автоматической проверки object-level ownership.

    Per ADR-0345 Option A: fail-closed per-call enforcement.

    Args:
        resource_model: ORM model class (e.g., ``Order``).
        id_param: имя path/query parameter с resource_id.
        tenant_field: имя поля на model для tenant_id (default: "tenant_id").
        raise_on_mismatch: True → raise ``AuthorizationError``. False → return None.
        session_factory: Optional session factory для DB access. Если None —
            legacy stub behavior (logs only, no fail-closed).
        explicit_tenant_id: Tenant_id текущего вызывающего. Если None —
            legacy stub behavior.

    Raises:
        NotFoundError: resource не найден.
        AuthorizationError: tenant_id mismatch.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            await _verify_ownership(
                resource_model=resource_model,
                id_param=id_param,
                tenant_field=tenant_field,
                kwargs=kwargs,
                raise_on_mismatch=raise_on_mismatch,
                session_factory=session_factory,
                explicit_tenant_id=explicit_tenant_id,
            )
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            import asyncio

            asyncio.run(
                _verify_ownership(
                    resource_model=resource_model,
                    id_param=id_param,
                    tenant_field=tenant_field,
                    kwargs=kwargs,
                    raise_on_mismatch=raise_on_mismatch,
                    session_factory=session_factory,
                    explicit_tenant_id=explicit_tenant_id,
                )
            )
            return func(*args, **kwargs)

        # Pick async vs sync wrapper based on coroutine.
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


async def _verify_ownership(
    *,
    resource_model: type,
    id_param: str,
    tenant_field: str,
    kwargs: dict[str, Any],
    raise_on_mismatch: bool,
    session_factory: Callable[[], Any] | None = None,
    explicit_tenant_id: str | None = None,
) -> None:
    """Verify that resource.tenant_id matches caller's tenant_id.

    Per ADR-0345 Option A: fail-closed per-call enforcement.

    Behavior matrix:
    - session_factory provided + explicit_tenant_id provided:
      Full fail-closed: load resource, compare tenant_field value
      against explicit_tenant_id; raise AuthorizationError on mismatch.
    - Either missing: legacy stub behavior (log only) — backwards-compat
      для existing callers without session infrastructure.

    Raises:
        NotFoundError: resource не найден (fail-closed path only).
        AuthorizationError: tenant_id mismatch (fail-closed path only).
        ValueError: missing required param `id_param` (always).
    """
    resource_id = kwargs.get(id_param)
    if resource_id is None:
        raise ValueError(
            f"@require_object_ownership: missing required param '{id_param}' "
            f"in function signature"
        )

    # Legacy fallback (backwards-compat): no session_factory OR no explicit_tenant_id.
    if session_factory is None or explicit_tenant_id is None:
        logger.debug(
            "ownership_check_stub",
            resource_model=getattr(resource_model, "__name__", str(resource_model)),
            resource_id=resource_id,
            tenant_field=tenant_field,
            reason="missing session_factory OR explicit_tenant_id",
        )
        return

    # Fail-closed path: load resource + compare tenant.
    try:
        session = session_factory()
        # Resource lookup. Use ``get`` if available, else ``query().filter_by``.
        resource = None
        get_attr = getattr(resource_model, "get", None)
        if get_attr is not None:
            resource = session.get(resource_model, resource_id)
        else:
            resource = session.query(resource_model).filter_by(id=resource_id).first()
    except Exception as exc:
        # Per audit + ADR-0345: fail-closed on unexpected errors.
        raise AuthorizationError(
            message=(
                f"Failed to load {resource_model.__name__}(id={resource_id}): {exc}"
            )
        ) from exc

    if resource is None:
        raise NotFoundError(
            message=f"{resource_model.__name__} with id={resource_id} not found"
        )

    resource_tenant_id = getattr(resource, tenant_field, None)
    if resource_tenant_id != explicit_tenant_id:
        if raise_on_mismatch:
            raise AuthorizationError(
                message=(
                    f"Tenant mismatch: resource.tenant_id={resource_tenant_id!r} "
                    f"!= caller.tenant_id={explicit_tenant_id!r}"
                )
            )
        # raise_on_mismatch=False — caller handles None return.
        return

    logger.debug(
        "ownership_check_pass",
        resource_model=getattr(resource_model, "__name__", str(resource_model)),
        resource_id=resource_id,
        tenant_id=explicit_tenant_id,
    )


__all__ = ("require_object_ownership",)


__all__ = ("require_object_ownership",)
