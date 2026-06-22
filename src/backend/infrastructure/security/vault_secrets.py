"""``VaultSecretsBackend`` — реализация :class:`SecretsBackend` поверх HashiCorp Vault (KV v2).

Wave 1.2 (S3): убирает stub ``NotImplementedError`` в
``plugins.composition.service_setup`` для ``SECRETS_BACKEND=vault``.

Свойства:

* lazy ``import hvac`` — модуль не требуется на dev-профиле;
* in-memory cache с TTL (по умолчанию 60 секунд), не превышающий
  ``VaultSecretRefresher.interval`` — иначе обновление секретов
  «отстаёт» от ротации;
* re-auth на ``hvac.exceptions.Forbidden`` / ``InvalidRequest`` через
  настраиваемую фабрику клиентов; одна попытка пере-логина перед
  пробросом ошибки caller'у;
* интерфейс совпадает с :class:`SecretsBackend` (см. core/interfaces/secrets.py).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.secrets import SecretsBackend
from src.backend.core.logging import get_logger
if TYPE_CHECKING:
    import hvac

__all__ = ("VaultBackendConfig", "VaultSecretsBackend")

_logger = get_logger("infrastructure.security.vault_secrets")

ClientFactory = Callable[[], "hvac.Client"]
"""Фабрика hvac-клиентов; вызывается при первом обращении и при re-auth."""


@dataclass(frozen=True, slots=True)
class VaultBackendConfig:
    """Конфигурация :class:`VaultSecretsBackend`.

    Attributes:
        addr: URL Vault-сервера.
        token: Токен (либо AppRole-token из ``VaultSecretRefresher``).
        mount: KV v2 mount-point (по умолчанию ``secret``).
        cache_ttl_s: TTL in-memory кеша значений (≤ refresher.interval).
    """

    addr: str
    token: str | None = None
    mount: str = "secret"
    cache_ttl_s: float = 60.0


class VaultSecretsBackend(SecretsBackend):
    """SecretsBackend поверх hvac (HashiCorp Vault KV v2).

    Args:
        addr: URL Vault-сервера; обычно ``http://vault:8200``.
        token: Vault-token (если ``None`` — ожидается, что ``client_factory``
            заполнит auth самостоятельно — например через AppRole).
        mount: KV v2 mount-point.
        cache_ttl_s: TTL in-memory кеша значений в секундах.
        client_factory: Опц. фабрика hvac-клиентов (для тестов / альтернативной
            аутентификации). Если ``None`` — конструируется ``hvac.Client``
            из ``addr``/``token``.
    """

    def __init__(
        self,
        *,
        addr: str,
        token: str | None = None,
        mount: str = "secret",
        cache_ttl_s: float = 60.0,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._addr = addr
        self._token = token
        self._mount = mount
        self._cache_ttl = cache_ttl_s
        self._client_factory = client_factory
        self._client: hvac.Client | None = None
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = asyncio.Lock()

    def _build_client(self) -> hvac.Client:
        """Строит hvac.Client lazy: import + auth на первом обращении."""
        if self._client_factory is not None:
            return self._client_factory()
        import hvac

        return hvac.Client(url=self._addr, token=self._token)

    def _get_client(self) -> hvac.Client:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _reauth(self) -> hvac.Client:
        """Сбрасывает кеш клиента и перестраивает его (для retry-once на Forbidden)."""
        _logger.warning("Vault re-auth: rebuilding client")
        self._client = self._build_client()
        return self._client

    async def get_secret(self, key: str) -> str | None:
        """Прочитать секрет ``key`` из KV v2 (с in-memory кешем).

        Поддерживается формат ключа:

        * ``"path/to/secret#field"`` — путь + конкретное поле в KV-объекте;
        * ``"path/to/secret"`` — путь, возвращает значение поля ``value``
          (если есть) либо stringified JSON всего объекта.
        """
        now = time.time()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] <= self._cache_ttl:
            return cached[1]

        path, field = self._split_key(key)

        async with self._lock:
            value = await asyncio.to_thread(self._read_kv_v2, path, field)
            self._cache[key] = (now, value)
            return value

    def _read_kv_v2(self, path: str, field: str | None) -> str | None:
        """Sync-чтение KV v2 с одной попыткой re-auth на Forbidden."""
        client = self._get_client()
        try:
            return self._do_read(client, path, field)
        except Exception as exc:
            if self._is_auth_error(exc):
                client = self._reauth()
                try:
                    return self._do_read(client, path, field)
                except Exception as second_exc:
                    _logger.error(
                        "Vault read failed after re-auth: %s/%s: %s",
                        self._mount,
                        path,
                        second_exc,
                    )
                    return None
            _logger.error("Vault read failed: %s/%s: %s", self._mount, path, exc)
            return None

    def _do_read(self, client: hvac.Client, path: str, field: str | None) -> str | None:
        response = client.secrets.kv.v2.read_secret_version(
            path=path, mount_point=self._mount
        )
        data: dict[str, Any] = response.get("data", {}).get("data", {})
        if field is not None:
            value = data.get(field)
            return None if value is None else str(value)
        if "value" in data:
            return str(data["value"])
        if not data:
            return None
        return str(data)

    @staticmethod
    def _is_auth_error(exc: BaseException) -> bool:
        """Распознать ошибки аутентификации hvac (Forbidden / InvalidRequest)."""
        try:
            import hvac.exceptions as hv_exc
        except ImportError:
            return False
        return isinstance(exc, (hv_exc.Forbidden, hv_exc.InvalidRequest))

    @staticmethod
    def _split_key(key: str) -> tuple[str, str | None]:
        if "#" in key:
            path, field = key.split("#", 1)
            return path, field
        return key, None

    async def set_secret(self, key: str, value: str) -> None:
        """Записать секрет (KV v2 patch с одним полем)."""
        path, field = self._split_key(key)
        field_name = field or "value"

        async with self._lock:
            await asyncio.to_thread(self._write_kv_v2, path, {field_name: value})
            self._cache.pop(key, None)

    def _write_kv_v2(self, path: str, secret: dict[str, str]) -> None:
        client = self._get_client()
        try:
            client.secrets.kv.v2.create_or_update_secret(
                path=path, secret=secret, mount_point=self._mount
            )
        except Exception as exc:
            if self._is_auth_error(exc):
                client = self._reauth()
                client.secrets.kv.v2.create_or_update_secret(
                    path=path, secret=secret, mount_point=self._mount
                )
            else:
                raise

    async def delete_secret(self, key: str) -> bool:
        """Удалить секрет (KV v2 destroy_secret_versions all-versions)."""
        path, _field = self._split_key(key)

        async with self._lock:
            existed = await asyncio.to_thread(self._delete_kv_v2, path)
            self._cache.pop(key, None)
            return existed

    def _delete_kv_v2(self, path: str) -> bool:
        client = self._get_client()
        try:
            client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path, mount_point=self._mount
            )
            return True
        except Exception as exc:
            if self._is_auth_error(exc):
                client = self._reauth()
                try:
                    client.secrets.kv.v2.delete_metadata_and_all_versions(
                        path=path, mount_point=self._mount
                    )
                    return True
                except Exception as _:
                    return False
            return False

    async def list_keys(self, prefix: str | None = None) -> list[str]:
        """Список ключей под ``prefix`` (вызывает ``list_secrets`` рекурсивно)."""
        base = prefix or ""

        async with self._lock:
            keys = await asyncio.to_thread(self._list_kv_v2, base)
        return sorted(keys)

    def _list_kv_v2(self, base: str) -> list[str]:
        client = self._get_client()
        try:
            response = client.secrets.kv.v2.list_secrets(
                path=base, mount_point=self._mount
            )
        except Exception as exc:
            if self._is_auth_error(exc):
                client = self._reauth()
                try:
                    response = client.secrets.kv.v2.list_secrets(
                        path=base, mount_point=self._mount
                    )
                except Exception as _:
                    return []
            else:
                return []
        raw_keys = response.get("data", {}).get("keys", [])
        return [f"{base.rstrip('/')}/{k}" if base else k for k in raw_keys]

    async def health_check(self) -> bool:
        """Проверка доступности Vault (для readiness-gate / fallback)."""
        try:
            client = self._get_client()
            return bool(await asyncio.to_thread(client.is_authenticated))
        except Exception as exc:
            _logger.warning("Vault health_check failed: %s", exc)
            return False
