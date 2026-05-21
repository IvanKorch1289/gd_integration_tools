"""Protocol ``CapabilityGatewayProtocol`` (ADR-NEW-4, Sprint 17).

Назначение:
    Абстрагирует :class:`CapabilityGate` для единого фасада авторизации
    (:class:`AuthorizationGateway`, ADR-NEW-1). Позволяет:

    * подменять реальный gate на test-double без зависимости от
      ``capabilities/`` подмодуля;
    * композировать gate в цепочку с другими policy-движками
      (CapabilityPolicy → Casbin → OPA) в :class:`AuthorizationGateway`;
    * декларировать капабилити плагина/route'а в едином API.

Реализация:
    :class:`src.backend.core.security.capabilities.gate.CapabilityGate`
    реализует этот Protocol через ``@runtime_checkable``.

Тестовый double:
    Любой объект с тремя методами (check / declare / list_allocated)
    автоматически удовлетворяет Protocol.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

__all__ = ("CapabilityGatewayProtocol",)


@runtime_checkable
class CapabilityGatewayProtocol(Protocol):
    """Унифицированный интерфейс capability-gate.

    Поведение каждого метода:

    * ``check(plugin, capability, scope)`` — проверяет, что плагин
      имеет декларацию capability с покрывающим scope; raise
      ``CapabilityDeniedError`` при denied.
    * ``declare(plugin, capabilities)`` — сохраняет декларацию плагина
      (обычно вызывается loader'ом до import ``entry_class``).
    * ``list_allocated(plugin)`` — возвращает имена capability,
      задекларированные для плагина (для audit и admin-UI).

    Notes:
        Все scope-параметры — строки. Соответствие scope-pattern и
        реального scope проверяется через ``ScopeMatcher`` (см.
        :mod:`capabilities.scope`). Сам Protocol не определяет
        конкретный формат scope — это контракт реализации.
    """

    def check(
        self, plugin: str, capability: str, scope: str | None = None
    ) -> None:
        """Проверить разрешение; raise при denied."""
        ...

    def declare(
        self, plugin: str, capabilities: Iterable[object]
    ) -> None:
        """Задекларировать capabilities плагина/route'а."""
        ...

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        """Список имён задекларированных capabilities для плагина."""
        ...
