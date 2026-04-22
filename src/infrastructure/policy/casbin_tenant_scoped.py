"""Tenant-scoped Casbin wrapper (IL-SEC2).

Проблема: существующий ``CasbinAdapter.enforce(subject, resource, action)`` не
учитывает ``tenant_id``. В multi-tenant SaaS пользователь с ролью
``orders_reader`` в tenant ``acme`` может получить доступ к orders любого
другого tenant-а (cross-tenant IDOR).

Решение: wrapper, который:

* читает текущий tenant из ContextVar
  (``src/core/tenancy/__init__.py::current_tenant``);
* передаёт tenant как 4-й позиционный аргумент в ``Enforcer.enforce(...)``;
* использует расширенную model
  ``[p, sub, obj, act, tenant] / m = ... && r.tenant == p.tenant``.

**Не breaking change для существующего CasbinAdapter.** Оба adapter-а
сосуществуют; новые модули должны использовать ``TenantScopedCasbin``.

Пример model-конфига (``policies/casbin_model_tenant.conf``)::

    [request_definition]
    r = sub, obj, act, tenant

    [policy_definition]
    p = sub, obj, act, tenant

    [role_definition]
    g = _, _

    [policy_effect]
    e = some(where (p.eft == allow))

    [matchers]
    m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act && r.tenant == p.tenant

Пример policy::

    p, admin, orders, read, tenant_acme
    p, admin, orders, read, tenant_beta

    g, alice, admin
    g, bob, admin

Тогда ``enforce("alice", "orders", "read")`` в контексте tenant ``acme``
разрешает доступ, а в контексте ``beta`` — запрещает (нет policy для bob
в beta-tenant).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.tenancy import current_tenant

if TYPE_CHECKING:
    from app.infrastructure.policy.casbin_adapter import CasbinAdapter


__all__ = ("TenantScopedCasbin",)


logger = logging.getLogger("policy.casbin_tenant")


class TenantScopedCasbin:
    """Casbin enforcer с автоматическим tenant-scoping-ом.

    Оборачивает существующий ``CasbinAdapter``; не модифицирует его.
    Читает ``current_tenant()`` из ContextVar; если tenant-контекст не
    установлен — deny (fail-closed), так как в multi-tenant
    окружении "no tenant" = "unknown caller".

    Параметры:
        base_adapter: существующий ``CasbinAdapter`` с загруженным
            ``casbin.Enforcer`` и расширенной model (4-арг policy).
        default_tenant_id: если задан, используется при отсутствии контекста
            (только для dev/test-окружений; в prod оставлять None).
    """

    def __init__(
        self,
        base_adapter: "CasbinAdapter",
        *,
        default_tenant_id: str | None = None,
    ) -> None:
        self._base = base_adapter
        self._default_tenant_id = default_tenant_id

    # ---------------------------------------------------------------- helpers

    def _resolve_tenant(self, explicit: str | None) -> str | None:
        """Приоритет: explicit > ContextVar > default > None."""
        if explicit:
            return explicit
        ctx = current_tenant()
        if ctx is not None and ctx.tenant_id:
            return ctx.tenant_id
        return self._default_tenant_id

    # ---------------------------------------------------------------- enforce

    def enforce(
        self,
        user_id: str,
        resource: str,
        action: str,
        tenant_id: str | None = None,
    ) -> bool:
        """Разрешён ли ``user_id`` выполнить ``action`` на ``resource`` в ``tenant``.

        * ``tenant_id`` можно передать явно; если ``None`` — берётся из
          ContextVar ``current_tenant``;
        * если tenant всё ещё ``None`` — **deny** (fail-closed).

        :returns: True если policy разрешает; False во всех прочих случаях.
        """
        tenant = self._resolve_tenant(tenant_id)
        if tenant is None:
            logger.warning(
                "TenantScopedCasbin.enforce: нет tenant в контексте "
                "(user=%s, resource=%s, action=%s) — deny",
                user_id,
                resource,
                action,
            )
            return False

        enforcer = self._base._ensure_enforcer()  # noqa: SLF001 — интеграция
        if enforcer is None:
            return False
        try:
            return bool(enforcer.enforce(user_id, resource, action, tenant))
        except Exception as exc:  # noqa: BLE001 — любая ошибка casbin → deny
            logger.error(
                "TenantScopedCasbin enforce fail (user=%s, resource=%s, "
                "action=%s, tenant=%s): %s",
                user_id,
                resource,
                action,
                tenant,
                exc,
            )
            return False

    # ----------------------------------------------------------- admin: policy

    def add_policy(
        self,
        user_id: str,
        resource: str,
        action: str,
        tenant_id: str,
    ) -> bool:
        """Добавить 4-арг policy ``(user, resource, action, tenant)``."""
        enforcer = self._base._ensure_enforcer()  # noqa: SLF001
        if enforcer is None:
            return False
        try:
            return bool(enforcer.add_policy(user_id, resource, action, tenant_id))
        except Exception as exc:  # noqa: BLE001
            logger.error("TenantScopedCasbin add_policy fail: %s", exc)
            return False

    def remove_policy(
        self,
        user_id: str,
        resource: str,
        action: str,
        tenant_id: str,
    ) -> bool:
        """Удалить ранее добавленную 4-арг policy."""
        enforcer = self._base._ensure_enforcer()  # noqa: SLF001
        if enforcer is None:
            return False
        try:
            return bool(
                enforcer.remove_policy(user_id, resource, action, tenant_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("TenantScopedCasbin remove_policy fail: %s", exc)
            return False

    # ------------------------------------------------------------ admin: role

    def add_role(self, user_id: str, role: str) -> bool:
        """Присвоить ``role`` пользователю ``user_id`` (глобально, не per-tenant).

        Для per-tenant ролей используйте 3-арг grouping policy через
        ``enforcer.add_named_grouping_policy("g", [user, role, tenant])``.
        """
        enforcer = self._base._ensure_enforcer()  # noqa: SLF001
        if enforcer is None:
            return False
        try:
            return bool(enforcer.add_role_for_user(user_id, role))
        except Exception as exc:  # noqa: BLE001
            logger.error("TenantScopedCasbin add_role fail: %s", exc)
            return False
