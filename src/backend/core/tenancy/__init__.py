"""Multi-tenancy — TenantContext + RLS + Redis prefix (G1).

Tenant resolver читает header ``X-Tenant-ID`` или subdomain, устанавливает
``TenantContext.current``. Все нижележащие слои (DB, Redis, logs,
metrics) используют контекст для изоляции.

Канонический тип контекста — :class:`src.backend.core.tenancy.context.TenantContext`
(единый источник правды, аудит Z-07). В ContextVar кладётся **только** он:
установка проходит через :func:`normalize_tenant_context`, которая приводит
совместимый объект (например, :class:`CapabilityTenant`) к каноническому типу
и отвергает рассинхрон (объект без ``tenant_id``) с ``TypeError``.
"""

from __future__ import annotations

from contextvars import ContextVar as ContextVar

from src.backend.core.tenancy.context import (
    SYSTEM_TENANT_ID,
    CapabilityTenant,
    TenantContext,
    TenantContextLike,
    normalize_tenant_context,
)

__all__ = (
    "SYSTEM_TENANT_ID",
    "CapabilityTenant",
    "QuotaExceeded",
    "QuotaTracker",
    "SLOEvaluation",
    "TenantContext",
    "TenantContextLike",
    "TenantSLO",
    "bind_tenant",
    "bind_tenant_from_metadata",
    "current_tenant",
    "get_principal_id",
    "get_tenant_id",
    "normalize_tenant_context",
    "set_tenant",
    "system_tenant_context",
    "tenant_scope",
    "unbind_tenant",
)


_current: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def _install(ctx: object) -> object:
    """Привести контекст к каноническому типу и установить его в ContextVar.

    Единая точка установки: любой путь (``set_tenant`` / ``bind_tenant`` /
    ``tenant_scope``) проходит через fail-closed нормализацию — рассинхрони-
    зированный контекст (без ``tenant_id``) не может попасть в ContextVar и
    увести проверку прав в tenant-less режим (аудит Z-07).

    Args:
        ctx: Контекст для установки.

    Returns:
        Токен ContextVar (для сброса через ``reset``).

    Raises:
        TypeError: объект не удовлетворяет контракту tenant-контекста.

    """
    return _current.set(normalize_tenant_context(ctx))


def current_tenant() -> TenantContext | None:
    """Вернуть активный tenant-контекст или ``None`` вне scope.

    Returns:
        Канонический :class:`TenantContext`, установленный в текущем
        ``ContextVar``, либо ``None``, если контекст ещё не выставлялся в
        текущей задаче.

    """
    return _current.get()


def set_tenant(ctx: TenantContext | None) -> None:
    """Установить ``ctx`` как активный тенант для текущей async-задачи.

    Args:
        ctx: Иммутабельный snapshot тенанта, который будет доступен через
            ``current_tenant()`` до выхода из ``tenant_scope``/задачи.
            ``None`` — снять контекст.

    Raises:
        TypeError: объект не удовлетворяет контракту tenant-контекста.
            Fail-closed: сломанный контекст (без ``tenant_id``) не должен
            попасть в ContextVar — иначе чтение ``ctx.tenant_id`` упало бы с
            ``AttributeError``, который глушится, и проверка прав ушла бы в
            tenant-less режим (аудит Z-07).

    """
    if ctx is None:
        _current.set(None)
        return
    _install(ctx)


def get_tenant_id() -> str:
    """Вернуть tenant_id активного тенанта или пустую строку.

    Convenience wrapper для использования в SQLAlchemy filters и других
    местах, где нужен строковый tenant_id.
    """
    ctx = _current.get()
    return ctx.tenant_id if ctx is not None else ""


def get_principal_id() -> str | None:
    """Вернуть principal_id активного tenant-контекста.

    Returns:
        Principal (плагин/route/user) активного контекста либо ``None``,
        если контекст не выставлен или principal не заявлен.

    """
    ctx = _current.get()
    if ctx is None:
        return None
    return ctx.principal_id


# Sentinel системного tenant'а (ADR-0448, вариант А) — см.
# ``src.backend.core.tenancy.context.SYSTEM_TENANT_ID``. Контекст с таким
# tenant_id означает **платформенный** scope: кросс-tenant запросы служебных
# потоков разрешены. Пустой tenant_id — fail-closed (запрос к tenant-aware
# сущности отклоняется). Отсутствие контекста — тоже платформенный scope:
# пользовательский контур tenant всегда выставляет (auth-middleware), а
# служебные потоки (планировщик, версионирование, репозитории) работают без
# контекста намеренно.
def system_tenant_context() -> "TenantContext":
    """Контекст платформенного (системного) scope (ADR-0448).

    Returns:
        ``TenantContext`` с tenant_id = :data:`SYSTEM_TENANT_ID`.

    """
    return TenantContext(tenant_id=SYSTEM_TENANT_ID, plan="enterprise", region="global")


class tenant_scope:
    """Контекст-менеджер на время обработки запроса."""

    def __init__(self, ctx: TenantContext) -> None:
        self._ctx = normalize_tenant_context(ctx)
        self._token = None

    def __enter__(self) -> TenantContext:
        self._token = _install(self._ctx)
        return self._ctx

    def __exit__(self, *args: object) -> None:
        if self._token is not None:
            _current.reset(self._token)


def bind_tenant(ctx: TenantContext) -> object:
    """Установить tenant на время ASGI-запроса и вернуть токен для сброса.

    ``set_tenant`` намеренно не возвращает токен: он рассчитан на
    использование внутри ``tenant_scope``. Async-middleware не может
    использовать синхронный context manager, поэтому нужен явный
    bind/unbind — иначе tenant предыдущего запроса утекает в следующий,
    что хуже отсутствия изоляции: доступ получает не свой principal,
    а чужой.

    Args:
        ctx: снимок тенанта, который должен быть виден вниз по стеку.

    Returns:
        Токен, который нужно передать в :func:`unbind_tenant` в ``finally``.

    Raises:
        TypeError: объект не удовлетворяет контракту tenant-контекста
            (fail-closed, см. :func:`set_tenant`).

    """
    return _install(ctx)


def unbind_tenant(token: object) -> None:
    """Снять tenant, установленный через :func:`bind_tenant`.

    Args:
        token: токен, полученный от :func:`bind_tenant`.

    """
    _current.reset(token)  # type: ignore[arg-type]


def bind_tenant_from_metadata(metadata: object) -> object | None:
    """Связать tenant с аутентифицированным principal'ом, если он заявлен.

    Единственный доверенный источник tenant — ``AuthContext.metadata``
    (SECURITY-P0-002). Заголовок ``X-Tenant-ID`` сюда не попадает намеренно.

    Args:
        metadata: ``AuthContext.metadata`` либо ``None``.

    Returns:
        Токен для :func:`unbind_tenant` либо ``None``, если tenant не
        заявлен и привязывать нечего (анонимный principal).

    """
    if not isinstance(metadata, dict):
        return None
    tenant_id = metadata.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        return None
    return bind_tenant(TenantContext(tenant_id=tenant_id))


# Re-exports после определения symbols (порядок важен для избежания циклов).
from src.backend.core.tenancy.quotas import QuotaExceeded, QuotaTracker
from src.backend.core.tenancy.slo import SLOEvaluation as SLOEvaluation
from src.backend.core.tenancy.slo import TenantSLO as TenantSLO
