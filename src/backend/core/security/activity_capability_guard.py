"""Capability guard для Temporal activities (Sprint 4 Wave E, V15 R-V15-1).

Назначение модуля:
    Реализует декоратор :func:`capability_guarded_activity`, который
    оборачивает Temporal-activity функцию и до её вызова проверяет
    декларации capability через :class:`CapabilityGate`. Если плагин
    не задекларировал требуемую capability — поднимается
    :class:`CapabilityDeniedError` и в audit-канал пишется событие.

Архитектурные принципы:
    * Feature-flag :attr:`FeatureFlags.activity_capability_gate_enabled`
      управляет включением проверки. При выключенном флаге обёртка
      превращается в NoOp (нулевой overhead, обратная совместимость).
    * :class:`CapabilityDeniedError` импортируется из существующей
      подсистемы :mod:`core.security.capabilities` (ADR-044), не
      дублируется.
    * Если runtime-контекст плагина недоступен (например, в unit-тесте
      без поднятого PluginLoaderV11) — обёртка пропускает проверку,
      записав WARNING в audit-канал. Это позволяет существующим
      activity'ям работать в legacy-сценариях без миграции.
    * temporalio импортируется лениво только для аннотаций; сам guard
      не вызывает Temporal API напрямую.

Использование:
    .. code-block:: python

        from src.backend.core.security.activity_capability_guard import (
            capability_guarded_activity,
        )

        @capability_guarded_activity(("db.read",))
        async def my_activity(payload: dict) -> dict:
            ...

    В :class:`ActivityBridge` обёртка применяется автоматически, если
    :attr:`ActivityDeclaration.required_capabilities` не пуст.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from src.backend.core.security.capabilities import CapabilityDeniedError, CapabilityGate

__all__ = (
    "CapabilityContext",
    "CapabilityDeniedError",
    "capability_guarded_activity",
    "get_active_capability_context",
    "set_active_capability_context",
)

_logger = logging.getLogger("core.security.activity_capability_guard")

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

AuditCallback = Callable[[dict[str, object]], None]
"""Сигнатура audit-callback'а: принимает event dict, ничего не возвращает."""


class CapabilityContext:
    """Контекст текущего плагина/route для capability-проверки.

    Activity-runtime обязан установить контекст до запуска первой
    capability-guarded функции через :func:`set_active_capability_context`.
    Bridge-слой (Temporal worker) делает это в момент диспатча.

    Attributes:
        plugin_name: Имя плагина или route'а — ключ для
            :meth:`CapabilityGate.check`.
        gate: Ссылка на runtime :class:`CapabilityGate`.
        scope: Опц. scope, по умолчанию подставляемый в check
            (``None`` если capability не требует scope).
        audit: Опц. дополнительный audit-callback для событий guard'а.
    """

    __slots__ = ("plugin_name", "gate", "scope", "audit")

    def __init__(
        self,
        *,
        plugin_name: str,
        gate: CapabilityGate,
        scope: str | None = None,
        audit: AuditCallback | None = None,
    ) -> None:
        self.plugin_name = plugin_name
        self.gate = gate
        self.scope = scope
        self.audit = audit


_active_context: CapabilityContext | None = None


def get_active_capability_context() -> CapabilityContext | None:
    """Получить активный capability-контекст (плагин/route runtime'а).

    Returns:
        Установленный :class:`CapabilityContext` или ``None``, если
        runtime-инициализация не была выполнена (legacy / unit-test).
    """
    return _active_context


def set_active_capability_context(context: CapabilityContext | None) -> None:
    """Установить активный capability-контекст.

    Args:
        context: Новый :class:`CapabilityContext` или ``None`` для сброса.
    """
    global _active_context  # noqa: PLW0603 — глобальный runtime-контекст
    _active_context = context


def _is_gate_enabled() -> bool:
    """Прочитать feature-flag, изолируя impl от ImportError при тестах.

    Returns:
        ``True`` если ``feature_flags.activity_capability_gate_enabled``
        включён. При ошибке импорта возвращается ``False`` (NoOp).
    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(feature_flags.activity_capability_gate_enabled)
    except Exception:  # noqa: BLE001 — fallback на NoOp при ошибке загрузки
        _logger.warning("Не удалось прочитать feature_flags; capability-gate NoOp")
        return False


def _emit_audit(context: CapabilityContext | None, event: dict[str, object]) -> None:
    """Записать audit-событие через callback контекста."""
    if context is None or context.audit is None:
        return
    try:
        context.audit(event)
    except Exception:  # noqa: BLE001 — audit не должен валить activity
        _logger.exception("Audit callback raised; suppressing")


def capability_guarded_activity(capabilities: tuple[str, ...]) -> Callable[[F], F]:
    """Декоратор для capability-проверки Temporal-activity функции.

    Args:
        capabilities: Кортеж имён capability, требуемых для выполнения.
            При пустом кортеже — обёртка не применяется (защита от
            случайного no-op декорирования).

    Returns:
        Decorator, оборачивающий async-функцию проверкой capability
        до её вызова.

    Поведение:
        * Если ``activity_capability_gate_enabled=False`` —
          обёртка передаёт управление сразу, без проверки.
        * Если контекст недоступен — пишет WARNING в audit-канал
          и допускает выполнение (`fail-open` для legacy).
        * Если контекст найден — для каждой capability вызывает
          :meth:`CapabilityGate.check` с ``context.scope``.
          При :class:`CapabilityDeniedError` событие денай-аудита
          уже было записано gate'ом; guard дополнительно пишет
          ``"event": "activity.capability.denied"``.
    """
    if not capabilities:
        # Пустой кортеж — возвращаем identity-декоратор.
        return lambda fn: fn

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _is_gate_enabled():
                return await fn(*args, **kwargs)

            context = get_active_capability_context()
            if context is None:
                _logger.warning(
                    "capability_guarded_activity: контекст не установлен; "
                    "пропуск проверки для %s (fail-open legacy)",
                    fn.__name__,
                )
                return await fn(*args, **kwargs)

            for capability in capabilities:
                try:
                    context.gate.check(context.plugin_name, capability, context.scope)
                except CapabilityDeniedError:
                    _emit_audit(
                        context,
                        {
                            "event": "activity.capability.denied",
                            "plugin": context.plugin_name,
                            "capability": capability,
                            "activity": getattr(fn, "__name__", "?"),
                            "scope": context.scope,
                        },
                    )
                    raise

            _emit_audit(
                context,
                {
                    "event": "activity.capability.granted",
                    "plugin": context.plugin_name,
                    "activity": getattr(fn, "__name__", "?"),
                    "capabilities": capabilities,
                    "scope": context.scope,
                },
            )
            return await fn(*args, **kwargs)

        # Сохраняем Temporal-маркер ``__activity_name__``, если был.
        if hasattr(fn, "__activity_name__"):
            wrapper.__activity_name__ = fn.__activity_name__  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
