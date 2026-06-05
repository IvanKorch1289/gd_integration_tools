"""ADR-044 — типизированные ошибки capability-gate.

Все ошибки наследуются от :class:`CapabilityError`, чтобы caller'ы могли
ловить весь класс одним `except`. Конкретные подтипы добавляют поля для
audit и Prometheus-меток.

Sprint 36 (V15 GAP, Subagent A): добавлен ``to_dict()`` для structured
logging / SIEM-export и опц. ``correlation_id`` для трассировки через
middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.security.capabilities.models import CapabilityRef

__all__ = (
    "CapabilityDeniedError",
    "CapabilityError",
    "CapabilityNotFoundError",
    "CapabilitySupersetError",
)


class CapabilityError(Exception):
    """Базовый класс ошибок capability-подсистемы."""

    correlation_id: str | None = None
    """Опц. request correlation_id (для audit tracing)."""

    def to_dict(self) -> dict[str, Any]:
        """Структурированная сериализация для audit / SIEM-export.

        Returns:
            ``dict`` с полями ``error_type``, ``message``, ``correlation_id``
            и (для подклассов) своими специфичными полями.
        """
        return {
            "error_type": type(self).__name__,
            "message": str(self),
            "correlation_id": self.correlation_id,
        }


class CapabilityDeniedError(CapabilityError):
    """Caller запросил ресурс, не покрытый его декларацией.

    Attributes:
        plugin: Имя плагина или маршрута, инициировавшего вызов.
        capability: Имя capability (``db.read``, ``net.outbound`` и т.п.).
        requested_scope: Scope, запрошенный в runtime.
        declared_scope: Scope, объявленный в манифесте (``None`` если
            capability вообще не декларирована).
        tenant: Tenant-id (для tenant-aware вызовов; ``"_system"`` по умолчанию).
        principal: Principal-id (имя плагина/route'а) для audit-контекста.
        correlation_id: Request correlation_id (опц.).
    """

    def __init__(
        self,
        *,
        plugin: str,
        capability: str,
        requested_scope: str | None,
        declared_scope: str | None,
        tenant: str = "_system",
        principal: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self.plugin = plugin
        self.capability = capability
        self.requested_scope = requested_scope
        self.declared_scope = declared_scope
        self.tenant = tenant
        # principal по умолчанию совпадает с plugin для backward compat
        # (если caller не передал явно).
        self.principal = principal if principal is not None else plugin
        self.correlation_id = correlation_id
        super().__init__(
            f"Capability denied for {plugin!r}: {capability}"
            f" (requested={requested_scope!r}, declared={declared_scope!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Структурированная сериализация для audit / SIEM-export.

        Returns:
            ``dict`` с полями: ``error_type``, ``capability``, ``tenant``,
            ``principal``, ``plugin``, ``scope``, ``declared_scope``,
            ``message``, ``correlation_id``.
        """
        return {
            "error_type": self.__class__.__name__,
            "capability": self.capability,
            "tenant": self.tenant,
            "principal": self.principal,
            "plugin": self.plugin,
            "scope": self.requested_scope,
            "declared_scope": self.declared_scope,
            "message": str(self),
            "correlation_id": self.correlation_id,
        }


class CapabilityNotFoundError(CapabilityError):
    """Имя capability отсутствует в :class:`CapabilityVocabulary`.

    Attributes:
        name: Имя capability, которое не найдено.
        correlation_id: Request correlation_id (опц.).
    """

    def __init__(self, *, name: str, correlation_id: str | None = None) -> None:
        self.name = name
        self.correlation_id = correlation_id
        super().__init__(f"Unknown capability: {name!r}")

    def to_dict(self) -> dict[str, Any]:
        """Структурированная сериализация для audit / SIEM-export.

        Returns:
            ``dict`` с полями: ``error_type``, ``capability`` (== ``name``),
            ``message``, ``correlation_id``.
        """
        return {
            "error_type": self.__class__.__name__,
            "capability": self.name,
            "message": str(self),
            "correlation_id": self.correlation_id,
        }


class CapabilitySupersetError(CapabilityError):
    """Route запросил capability, не покрываемую плагинами + ядром.

    Используется :class:`RouteLoader` при проверке инварианта
    V11.1a: ``route.capabilities ⊆ union(plugin.capabilities) ∪ core_public``.
    """

    def __init__(self, *, route: str, offending: tuple[CapabilityRef, ...]) -> None:
        self.route = route
        self.offending = offending
        names = ", ".join(f"{c.name}({c.scope!r})" for c in offending)
        super().__init__(
            f"Route {route!r} requests capabilities not covered by "
            f"requires_plugins or core public set: {names}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Структурированная сериализация для audit / SIEM-export.

        Returns:
            ``dict`` с полями: ``error_type``, ``route``, ``offending`` (список
            ``{"name": ..., "scope": ...}``), ``message``, ``correlation_id``.
        """
        return {
            "error_type": self.__class__.__name__,
            "route": self.route,
            "offending": [{"name": c.name, "scope": c.scope} for c in self.offending],
            "message": str(self),
            "correlation_id": self.correlation_id,
        }
