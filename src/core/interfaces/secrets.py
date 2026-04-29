"""ABC ``SecretsBackend`` — контракт хранения секретов.

Wave 21.3c. Реализации:

* :class:`infrastructure.secrets.env_secrets.EnvSecretsBackend` — .env / os.environ
  (для dev_light — без Vault);
* (планируется) ``VaultSecretsBackend`` — HashiCorp Vault обёртка над текущим
  ``VaultClient`` (используется в production).

Контракт намеренно асинхронный: даже env-реализация декларирует ``async``
для единообразия с Vault, где запрос идёт по сети.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

__all__ = ("SecretsBackend",)


class SecretsBackend(ABC):
    """Контракт хранения секретов (kv-store с TTL/версионированием опционально)."""

    @abstractmethod
    async def get_secret(self, key: str) -> str | None:
        """Возвращает значение секрета по ключу или ``None``, если отсутствует.

        Реализация ДОЛЖНА быть идемпотентной — повторный вызов с тем же ключом
        возвращает тот же результат до явного ``set_secret``/``delete_secret``.
        """
        ...

    @abstractmethod
    async def set_secret(self, key: str, value: str) -> None:
        """Устанавливает (или перезаписывает) значение секрета."""
        ...

    @abstractmethod
    async def delete_secret(self, key: str) -> bool:
        """Удаляет секрет; возвращает ``True``, если секрет существовал."""
        ...

    @abstractmethod
    async def list_keys(self, prefix: str | None = None) -> list[str]:
        """Возвращает отсортированный список ключей (опционально с префиксом)."""
        ...
