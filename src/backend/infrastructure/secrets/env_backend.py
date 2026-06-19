"""Env-fallback backend для :class:`SecretBroker` (V15 S1).

Используется в dev-окружении или когда Vault недоступен. Маппит
имя секрета в env-переменную: ``db/postgres`` → ``DB__POSTGRES``
(double-underscore подобно pydantic settings).

Versioning не поддерживается — :meth:`get_versioned` всегда возвращает
``version=0`` (current). Rotation поллингом env-переменных бессмыслен;
для rotation подключайте :class:`VaultBackend`.

Совместим с deprecated ``infrastructure.security.env_secrets`` —
последний оставлен как alias до S0-cleanup К5.
"""

from __future__ import annotations

import os

from src.backend.infrastructure.secrets.broker import SecretValue

__all__ = ("EnvBackend",)


class EnvBackend:
    """Простой backend, читающий секрет из переменной окружения.

    Args:
        prefix: Опц. префикс для env-имени (``app__``).
    """

    def __init__(self, *, prefix: str = "") -> None:
        self._prefix = prefix

    def get(self, name: str) -> SecretValue:
        """Get secret value from environment.

        Args:
            name: Secret name (e.g. 'db/postgres').

        Returns:
            SecretValue with name, value, and version.

        Raises:
            KeyError: If secret not found in environment.
        """
        env_name = self._env_name(name)
        value = os.environ.get(env_name)
        if value is None:
            raise KeyError(f"Secret {name!r} not found in env (lookup={env_name!r})")
        return SecretValue(name=name, value=value, version=0)

    def get_versioned(self, name: str, version: int) -> SecretValue:
        """Get secret value by name and version (env ignores version).

        Args:
            name: Secret name.
            version: Version number (ignored for env backend).

        Returns:
            SecretValue with current value.
        """
        # Env не version-aware; вернуть текущий снимок.
        return self.get(name)

    def _env_name(self, name: str) -> str:
        """``db/postgres`` → ``DB__POSTGRES`` с опц. префиксом."""
        candidate = name.replace("/", "__").replace("-", "_").upper()
        return f"{self._prefix.upper()}{candidate}" if self._prefix else candidate
