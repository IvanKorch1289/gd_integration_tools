"""Caller-aware namespace для capability-проверок (ADR-0430).

Контекст
--------
Фасады ядра (``StorageFacade``, ``UnifiedCacheFacade``,
``ExternalDatabaseFacade``, ``OutboundHttpClient``) создаются в composition
root с фиксированным namespace'ом платформы (``"system"`` / ``"core"``).
Из-за этого проверка capability шла под baseline'ом платформы, и декларации
роута (``route.toml`` → ``storage.*`` / ``db.*`` / ``cache.*``) на неё не
влияли: автор не мог ограничить свой роут (ADR-0416 §Открытое).

Решение
-------
Namespace вызывающего (route_id) передаётся через :class:`ContextVar`:
движок DSL-маршрута привязывает его на время исполнения, а фасады
используют caller-namespace вместо платформенного.

Безопасная деградация: если у вызывающего **нет** деклараций, привязка не
выставляется → фасад проверяет под своим платформенным namespace'ом (поведение
до ADR-0430). Поэтому включение caller-aware проверки не ломает существующие
роуты, а постепенно переводит их на явные декларации (рэтчет, ADR-0430 §3).
"""

from __future__ import annotations

from contextvars import ContextVar, Token

__all__ = (
    "bind_caller_namespace",
    "current_caller_namespace",
    "effective_plugin",
    "reset_caller_namespace",
)

_caller_namespace: ContextVar[str | None] = ContextVar(
    "capability_caller_namespace", default=None
)
"""Namespace вызывающего (``route_id``) для capability-проверок."""


def bind_caller_namespace(namespace: str | None) -> Token[str | None]:
    """Привязать namespace вызывающего.

    Args:
        namespace: Namespace вызывающего (``route_id``) или ``None`` —
            снять привязку (проверка идёт под namespace'ом платформы).

    Returns:
        Токен для :func:`reset_caller_namespace`.

    """
    return _caller_namespace.set(namespace)


def reset_caller_namespace(token: Token[str | None]) -> None:
    """Снять привязку namespace вызывающего.

    Args:
        token: Токен, полученный от :func:`bind_caller_namespace`.

    """
    _caller_namespace.reset(token)


def current_caller_namespace() -> str | None:
    """Текущий namespace вызывающего (``None`` — проверка под платформой)."""
    return _caller_namespace.get()


def effective_plugin(fallback: str) -> str:
    """Namespace для capability-проверки.

    Args:
        fallback: Платформенный namespace фасада (``"system"`` / ``"core"``).

    Returns:
        Namespace вызывающего, если он привязан, иначе ``fallback``.

    """
    return _caller_namespace.get() or fallback
