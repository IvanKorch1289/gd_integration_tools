"""ADR-044 — типизированные ошибки capability-gate.

Все ошибки наследуются от :class:`CapabilityError`, чтобы caller'ы могли
ловить весь класс одним `except`. Конкретные подтипы добавляют поля для
audit и Prometheus-меток.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


class CapabilityDeniedError(CapabilityError):
    """Caller запросил ресурс, не покрытый его декларацией.

    Attributes:
        plugin: Имя плагина или маршрута, инициировавшего вызов.
        capability: Имя capability (``db.read``, ``net.outbound`` и т.п.).
        requested_scope: Scope, запрошенный в runtime.
        declared_scope: Scope, объявленный в манифесте (``None`` если
            capability вообще не декларирована).
    """

    def __init__(
        self,
        *,
        plugin: str,
        capability: str,
        requested_scope: str | None,
        declared_scope: str | None,
    ) -> None:
        self.plugin = plugin
        self.capability = capability
        self.requested_scope = requested_scope
        self.declared_scope = declared_scope
        super().__init__(
            f"Capability denied for {plugin!r}: {capability}"
            f" (requested={requested_scope!r}, declared={declared_scope!r})"
        )


class CapabilityNotFoundError(CapabilityError):
    """Имя capability отсутствует в :class:`CapabilityVocabulary`."""

    def __init__(self, *, name: str) -> None:
        self.name = name
        super().__init__(f"Unknown capability: {name!r}")


class CapabilitySupersetError(CapabilityError):
    """Route запросил capability, не покрываемую плагинами + ядром.

    Используется :class:`RouteLoader` при проверке инварианта
    V11.1a: ``route.capabilities ⊆ union(plugin.capabilities) ∪ core_public``.
    """

    def __init__(self, *, route: str, offending: tuple["CapabilityRef", ...]) -> None:
        self.route = route
        self.offending = offending
        names = ", ".join(f"{c.name}({c.scope!r})" for c in offending)
        super().__init__(
            f"Route {route!r} requests capabilities not covered by "
            f"requires_plugins or core public set: {names}"
        )
