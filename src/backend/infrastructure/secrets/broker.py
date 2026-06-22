"""SecretBroker — единый фасад чтения секретов (V15 S1+S3).

Контракт:

* ``get_secret(name)`` — вернуть текущую версию (с capability-check
  ``secrets.read.<name>``);
* ``get_versioned(name, version)`` — конкретная версия (KV v2);
* ``subscribe_rotation(name, callback)`` — push-нотификация при
  обнаружении новой версии (без рестарта).

Backend pluggable: :class:`VaultBackend` (KV v2 через ``hvac``) или
:class:`EnvBackend` (env-переменные для dev).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.backend.core.logging import get_logger
__all__ = (
    "SecretBackend",
    "SecretBroker",
    "SecretBrokerImpl",
    "SecretValue",
    "SubscriberCallback",
)

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Снимок одного секрета.

    Attributes:
        name: Полный путь секрета (``secret/data/db/postgres``).
        value: Strint-значение (для KV — поле ``value`` или весь dict).
        version: Версия (KV v2); 0 если backend versioning не поддерживает.
    """

    name: str
    value: str
    version: int = 0


SubscriberCallback = Callable[[SecretValue], None]
"""Вызывается :class:`RotationScheduler` при обнаружении новой версии."""

CapabilityChecker = Callable[[str, str, str | None], None]
"""(plugin, capability, scope) -> None; raise при denied."""


class SecretBackend(Protocol):
    """Источник секретов для :class:`SecretBrokerImpl`."""

    def get(self, name: str) -> SecretValue:
        """Вернуть текущую версию секрета."""
        ...

    def get_versioned(self, name: str, version: int) -> SecretValue:
        """Вернуть конкретную версию (KV v2). 0 ⇔ current."""
        ...


class SecretBroker(Protocol):
    """Public-контракт фасада секретов."""

    def get_secret(self, name: str) -> SecretValue:
        """Текущая версия секрета (с capability-check)."""
        ...

    def get_versioned(self, name: str, version: int) -> SecretValue:
        """Конкретная версия секрета."""
        ...

    def subscribe_rotation(self, name: str, callback: SubscriberCallback) -> None:
        """Подписка на ротацию секрета.

        Callback вызывается при обнаружении новой версии. Вызов
        ``unsubscribe`` (см. :meth:`unsubscribe_rotation`).
        """
        ...

    def unsubscribe_rotation(self, name: str, callback: SubscriberCallback) -> None:
        """Снять подписку."""
        ...


class SecretBrokerImpl:
    """Реализация :class:`SecretBroker` поверх :class:`SecretBackend`.

    Args:
        backend: Источник секретов (Vault / env).
        capability_check: Опц. ``CapabilityGate.check`` — каждый
            ``get_secret(name)`` валидируется как
            ``(plugin, "secrets.read", name)``.
        plugin: Имя caller'а (для capability-event'а).
    """

    def __init__(
        self,
        *,
        backend: SecretBackend,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "core",
    ) -> None:
        self._backend = backend
        self._check = capability_check
        self._plugin = plugin
        self._subscribers: dict[str, list[SubscriberCallback]] = {}

    def get_secret(self, name: str) -> SecretValue:
        """Get secret value with capability check.

        Args:
            name: Secret name.

        Returns:
            SecretValue from backend.

        Raises:
            CapabilityDenied: If capability check fails.
        """
        if self._check is not None:
            self._check(self._plugin, "secrets.read", name)
        return self._backend.get(name)

    def get_versioned(self, name: str, version: int) -> SecretValue:
        """Get secret value by version with capability check.

        Args:
            name: Secret name.
            version: Version number.

        Returns:
            SecretValue from backend.

        Raises:
            CapabilityDenied: If capability check fails.
        """
        if self._check is not None:
            self._check(self._plugin, "secrets.read", name)
        return self._backend.get_versioned(name, version)

    def subscribe_rotation(self, name: str, callback: SubscriberCallback) -> None:
        """Subscribe to secret rotation events.

        Args:
            name: Secret name to watch.
            callback: Callback to invoke on rotation.
        """
        self._subscribers.setdefault(name, []).append(callback)

    def unsubscribe_rotation(self, name: str, callback: SubscriberCallback) -> None:
        """Unsubscribe from secret rotation events.

        Args:
            name: Secret name.
            callback: Callback to remove.
        """
        if name in self._subscribers:
            try:
                self._subscribers[name].remove(callback)
            except ValueError:
                pass

    def list_subscribers(self, name: str) -> tuple[SubscriberCallback, ...]:
        """Снимок подписчиков (используется :class:`RotationScheduler`)."""
        return tuple(self._subscribers.get(name, ()))

    def notify_rotation(self, snapshot: SecretValue) -> None:
        """Сообщить подписчикам об обновлённом секрете.

        Используется :class:`RotationScheduler` после успешной проверки
        новой версии. Падения отдельных callback'ов логируются и не
        прерывают рассылку остальным.
        """
        for callback in self.list_subscribers(snapshot.name):
            try:
                callback(snapshot)
            except Exception as exc:
                _logger.warning(
                    "secret_broker.subscriber_failed name=%s err=%s", snapshot.name, exc
                )
