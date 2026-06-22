"""HashiCorp Vault backend для :class:`SecretBroker` (V15 S1+S3).

Поддерживает:

* KV v2 (mount ``secret/`` по умолчанию);
* AppRole authentication (``role_id`` + ``secret_id`` через env);
* Token authentication (через ``VAULT_TOKEN``);
* version metadata (для rotation polling).

Зависимость ``hvac`` уже в pyproject (``hvac>=2.3.0,<3.0.0``).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.secrets.broker import SecretValue

__all__ = ("VaultBackend", "VaultConfig")

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class VaultConfig:
    """Параметры подключения к Vault.

    Attributes:
        url: Базовый URL Vault.
        token: Vault token (или None — будет ``role_id``/``secret_id``).
        role_id: AppRole role_id (если auth=approle).
        secret_id: AppRole secret_id.
        mount_point: KV v2 mount-point (по умолчанию ``secret``).
        namespace: Опц. Vault Enterprise namespace.
    """

    url: str
    token: str | None = None
    role_id: str | None = None
    secret_id: str | None = None
    mount_point: str = "secret"
    namespace: str | None = None

    @classmethod
    def from_env(cls) -> VaultConfig:
        """Собрать конфиг из стандартных env-переменных.

        Поддерживает ``VAULT_ADDR``, ``VAULT_TOKEN``, ``VAULT_ROLE_ID``,
        ``VAULT_SECRET_ID``, ``VAULT_MOUNT``, ``VAULT_NAMESPACE``.
        """
        return cls(
            url=os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"),
            token=os.environ.get("VAULT_TOKEN"),
            role_id=os.environ.get("VAULT_ROLE_ID"),
            secret_id=os.environ.get("VAULT_SECRET_ID"),
            mount_point=os.environ.get("VAULT_MOUNT", "secret"),
            namespace=os.environ.get("VAULT_NAMESPACE"),
        )


class VaultBackend:
    """KV v2 backend для :class:`SecretBroker`.

    Args:
        config: Параметры подключения.
        client: Опц. инжекция тестового ``hvac.Client`` (для unit-тестов).

    Авторизация выбирается приоритетно: token → AppRole. Если ни один
    не задан — :class:`RuntimeError` при первом запросе.
    """

    def __init__(self, *, config: VaultConfig, client: Any | None = None) -> None:
        self._config = config
        self._client = client

    def _ensure_client(self) -> Any:
        """Lazy-init hvac.Client с выбранным методом auth (blocking-safe).

        Note:
            When called from async context, use ``_ensure_client_async`` instead
            to avoid blocking the event loop on hvac.auth.approle.login().
        """
        if self._client is not None:
            return self._client

        try:
            import hvac
        except ImportError as exc:  # pragma: no cover — hvac уже в стеке
            raise RuntimeError(
                "hvac не установлен; добавьте 'hvac>=2.3.0' в зависимости"
            ) from exc

        client = hvac.Client(url=self._config.url, namespace=self._config.namespace)
        if self._config.token:
            client.token = self._config.token
        elif self._config.role_id and self._config.secret_id:
            # For truly sync callers the blocking is acceptable since they are
            # not on the async event loop's hot path.
            client.auth.approle.login(
                role_id=self._config.role_id, secret_id=self._config.secret_id
            )
        else:
            raise RuntimeError(
                "Vault auth не сконфигурирован: задайте VAULT_TOKEN либо "
                "VAULT_ROLE_ID + VAULT_SECRET_ID"
            )
        self._client = client
        return client

    async def _ensure_client_async(self) -> Any:
        """Async version of _ensure_client for use in async methods.

        Runs hvac.auth.approle.login() in an executor to avoid blocking the
        event loop (hvac library is synchronous).
        """
        if self._client is not None:
            return self._client

        try:
            import hvac
        except ImportError as exc:  # pragma: no cover — hvac уже в стеке
            raise RuntimeError(
                "hvac не установлен; добавьте 'hvac>=2.3.0' в зависимости"
            ) from exc

        client = hvac.Client(url=self._config.url, namespace=self._config.namespace)
        if self._config.token:
            client.token = self._config.token
        elif self._config.role_id and self._config.secret_id:
            # hvac.auth.approle.login() is blocking — run in executor to avoid
            # blocking the async event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: client.auth.approle.login(
                    role_id=self._config.role_id, secret_id=self._config.secret_id
                ),
            )
        else:
            raise RuntimeError(
                "Vault auth не сконфигурирован: задайте VAULT_TOKEN либо "
                "VAULT_ROLE_ID + VAULT_SECRET_ID"
            )
        self._client = client
        return client

    def get(self, name: str) -> SecretValue:
        """Прочитать current version KV v2 secret'а (sync, backward compat)."""
        client = self._ensure_client()
        response = client.secrets.kv.v2.read_secret_version(
            path=name, mount_point=self._config.mount_point
        )
        return _unpack_kv_v2(name, response)

    async def get_versioned(self, name: str, version: int) -> SecretValue:
        """Прочитать конкретную версию KV v2 secret'а (0 → current)."""
        client = await self._ensure_client_async()
        kwargs: dict[str, Any] = {"path": name, "mount_point": self._config.mount_point}
        if version > 0:
            kwargs["version"] = version
        response = client.secrets.kv.v2.read_secret_version(**kwargs)
        return _unpack_kv_v2(name, response)

    async def get_metadata(self, name: str) -> dict[str, Any]:
        """Прочитать metadata KV v2 (нужно :class:`RotationScheduler`)."""
        client = await self._ensure_client_async()
        meta = client.secrets.kv.v2.read_secret_metadata(
            path=name, mount_point=self._config.mount_point
        )
        if isinstance(meta, dict):
            return meta.get("data", {})
        return {}


def _unpack_kv_v2(name: str, response: Any) -> SecretValue:
    """Извлечь ``value`` + ``version`` из hvac KV v2 ответа.

    KV v2 структура: ``{"data": {"data": {...}, "metadata": {"version": N}}}``.
    Для совместимости с разными формами хранения значения мы поддерживаем:

    * ``data["value"]`` — единственное поле value;
    * иначе — JSON-сериализация всего ``data`` dict'а.
    """
    if not isinstance(response, dict):
        raise RuntimeError(f"Vault: unexpected response type for {name!r}")
    data_block = response.get("data", {}) or {}
    payload = data_block.get("data") if "data" in data_block else data_block
    metadata = data_block.get("metadata", {}) or {}
    version = int(metadata.get("version", 0))

    if isinstance(payload, dict) and "value" in payload:
        value = str(payload["value"])
    else:
        # Сериализуем весь dict в JSON для downstream-парсинга.
        import json

        value = json.dumps(payload, sort_keys=True)
    return SecretValue(name=name, value=value, version=version)
