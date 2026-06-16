"""Multi-tenancy — TenantContext + RLS + Redis prefix (G1).

Tenant resolver читает header ``X-Tenant-ID`` или subdomain, устанавливает
``TenantContext.current``. Все нижележащие слои (DB, Redis, logs,
metrics) используют контекст для изоляции.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

__all__ = (
    "QuotaExceeded",
    "QuotaTracker",
    "TenantContext",
    "current_tenant",
    "get_tenant_id",
    "set_tenant",
    "tenant_scope",
)


@dataclass(slots=True, frozen=True)
class TenantContext:
    """Иммутабельный snapshot активного тенанта в пределах одного запроса.

    Attributes:
        tenant_id: Уникальный идентификатор организации (используется для
            изоляции данных, префикса Redis-ключей и routing).
        plan: Тарифный план (``free`` / ``basic`` / ``pro`` / ``enterprise``);
            определяет набор доступных функций и квот.
        region: Географический регион тенанта (для региональной маршрутизации
            и data-residency). По умолчанию ``ru``.
        rate_limit: Лимит запросов в минуту для тенанта; используется
            middleware и quota tracker'ом.
    """

    tenant_id: str
    plan: str = "free"  # free/basic/pro/enterprise
    region: str = "ru"
    rate_limit: int = 100  # req/min


_current: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def current_tenant() -> TenantContext | None:
    """Вернуть активный ``TenantContext`` или ``None`` вне scope.

    Returns:
        ``TenantContext``, установленный в текущем ``ContextVar``, или
        ``None``, если ``set_tenant`` ещё не вызывался в текущей задаче.
    """
    return _current.get()


def set_tenant(ctx: TenantContext) -> None:
    """Установить ``ctx`` как активный тенант для текущей async-задачи.

    Args:
        ctx: Иммутабельный snapshot тенанта, который будет доступен через
            ``current_tenant()`` до выхода из ``tenant_scope``/задачи.
    """
    _current.set(ctx)


def get_tenant_id() -> str:
    """Вернуть tenant_id активного тенанта или пустую строку.

    Convenience wrapper для использования в SQLAlchemy filters и других
    местах, где нужен строковый tenant_id.
    """
    ctx = _current.get()
    return ctx.tenant_id if ctx is not None else ""


class tenant_scope:
    """Контекст-менеджер на время обработки запроса."""

    def __init__(self, ctx: TenantContext) -> None:
        self._ctx = ctx
        self._token = None

    def __enter__(self) -> TenantContext:
        self._token = _current.set(self._ctx)
        return self._ctx

    def __exit__(self, *args: object) -> None:
        if self._token is not None:
            _current.reset(self._token)


# Re-exports после определения symbols (порядок важен для избежания циклов).
from src.backend.core.tenancy.quotas import QuotaExceeded, QuotaTracker  # noqa: E402
