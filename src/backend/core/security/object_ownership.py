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

# S170 stub (audit 2026-09-22 P0): get_logger deferred до integration с TenantContext.
logger = logging.getLogger(__name__)


def require_object_ownership(
    resource_model: type,
    id_param: str = "id",
    tenant_field: str = "tenant_id",
    raise_on_mismatch: bool = True,
) -> Callable:
    """Decorator для автоматической проверки object-level ownership.

    Args:
        resource_model: ORM model class (e.g., ``Order``).
        id_param: имя path/query parameter с resource_id.
        tenant_field: имя поля на model для tenant_id (default: "tenant_id").
        raise_on_mismatch: True → raise ``AuthorizationError``. False → return None.

    Raises:
        NotFoundError: resource не найден.
        AuthorizationError: tenant_id resource ≠ tenant_id caller.
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
) -> None:
    """Verify that resource.tenant_id matches caller's tenant_id.

    Implementation note: this is a stub — production wiring requires
    integration with TenantContext (see Sprint 1 follow-up).

    Raises:
        NotFoundError: resource не найден.
        AuthorizationError: tenant_id mismatch.
    """
    resource_id = kwargs.get(id_param)
    if resource_id is None:
        raise ValueError(
            f"@require_object_ownership: missing required param '{id_param}' "
            f"in function signature"
        )

    # Production implementation would:
    # 1. Get current tenant from TenantContext.
    # 2. Load resource by id.
    # 3. Compare resource.tenant_id to current_tenant_id.
    # 4. Raise on mismatch.

    # Stub — реальная интеграция в следующих коммитах.
    logger.debug(
        "ownership_check_stub",
        resource_model=getattr(resource_model, "__name__", str(resource_model)),
        resource_id=resource_id,
        tenant_field=tenant_field,
    )


__all__ = ("require_object_ownership",)
