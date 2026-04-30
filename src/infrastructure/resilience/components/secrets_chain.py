"""Wiring W26.4: Vault → .env + keyring.

Контракт callable: ``async def secret_resolve(ref: str) -> str | None``.

* Primary — HashiCorp Vault через ``hvac``.
* Fallback — env-переменные (``os.environ``) + ``keyring`` (опционально,
  только если установлен).

Поскольку ABC ``SecretsBackend`` (``core/interfaces/secrets.py``) ранее был
заблокирован permission system (см. W24 deferred), здесь используется
прямой fallback без ABC. После разблокировки ABC этот wiring можно
переключить через DI.

``ref`` интерпретируется как:
    * ``"VAR_NAME"``        → читается ``os.environ["VAR_NAME"]``;
    * ``"vault:path:key"``  → ``vault.read(path)["data"]["data"][key]``;
    * ``"keyring:service:user"`` → ``keyring.get_password(service, user)``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable

__all__ = (
    "SecretResolveCallable",
    "build_secrets_fallbacks",
    "build_secrets_primary",
)

logger = logging.getLogger(__name__)

SecretResolveCallable = Callable[[str], Awaitable[str | None]]


async def _vault_resolve(ref: str) -> str | None:
    """Primary: Vault KV v2."""
    from hvac import Client  # type: ignore[import-untyped]

    if not ref.startswith("vault:"):
        # Поддерживаем простой ref-формат: считаем ref ключом в дефолтном пути.
        path, _, key = ref.partition(":")
        path = path or "default"
        key = key or ref
    else:
        _, path, key = ref.split(":", 2)

    addr = os.environ.get("VAULT_ADDR")
    token = os.environ.get("VAULT_TOKEN")
    if not addr or not token:
        raise RuntimeError("Vault не сконфигурирован: VAULT_ADDR/TOKEN отсутствуют")

    client = Client(url=addr, token=token)
    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed")
    response = client.secrets.kv.v2.read_secret_version(path=path)
    data = response.get("data", {}).get("data", {})
    value = data.get(key)
    return str(value) if value is not None else None


async def _env_keyring_resolve(ref: str) -> str | None:
    """Fallback: env-переменная или keyring (если установлен)."""
    if ref.startswith("keyring:"):
        try:
            import keyring  # type: ignore[import-untyped]
        except ImportError:
            return None
        _, service, user = ref.split(":", 2)
        return keyring.get_password(service, user)
    # Default: env-переменная.
    var_name = ref.split(":")[-1]
    return os.environ.get(var_name)


def build_secrets_primary() -> SecretResolveCallable:
    return _vault_resolve


def build_secrets_fallbacks() -> dict[str, SecretResolveCallable]:
    return {"env_keyring": _env_keyring_resolve}
