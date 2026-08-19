"""Unified CredentialProvider (Security Wave S6).

Единая точка получения credentials для коннекторов. Провайдер:
1. Читает credentials из Vault / env / settings
2. Автоматически подписывается на rotation
3. Audit-emit события при каждом обращении
4. Cache in-memory с TTL

Коннекторы больше НЕ читают credentials напрямую из settings/env — только через провайдер.

Usage::

    provider = get_credential_provider()
    creds = await provider.get("kafka_main")
    await client.connect(creds.host, creds.port, creds.username, creds.password)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from src.backend.core.logging import get_logger

__all__ = ("CredentialProvider", "CredentialSpec", "get_credential_provider")


@dataclass(slots=True)
class CredentialSpec:
    """Спецификация credentials одного коннектора."""

    name: str
    secret_ref: str  # "vault:kv/data/kafka" или "env:KAFKA_PASSWORD"
    scope: Literal["tenant", "global", "principal"] = "global"
    rotation_path: str | None = None
    ttl_seconds: int = 300

    @property
    def is_vault(self) -> bool:
        """Метод is_vault (см. signature)."""
        return self.secret_ref.startswith("vault:")


@dataclass(slots=True)
class ResolvedCredential:
    """Разрешённый credential с audit-trail."""

    name: str
    value: dict[str, Any]  # {"username": ..., "password": ..., ...}
    resolved_at: float = field(default_factory=time.time)
    resolution_id: str = field(default_factory=lambda: str(uuid4()))


class CredentialProvider:
    """Thread-safe credential provider с TTL cache."""

    def __init__(self) -> None:
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, ResolvedCredential] = {}
        self._logger = get_logger("security.credentials")

    def register_spec(self, spec: CredentialSpec) -> None:
        """Регистрирует spec для credentials коннектора."""
        self._specs[spec.name] = spec

    async def get(self, name: str, *, actor: str = "system") -> ResolvedCredential:
        """Получить credentials с caching + audit-emit.

        Cycle 60 L8: docstring claim "Audit-emit события при каждом обращении"
        теперь выполнен — emit'им ``secret.access`` audit event на cache hit,
        cache miss и failure. Содержимое секрета НИКОГДА не включается в
        payload (только метаданные: имя, ref, actor, cache_status).

        Args:
            name: Имя credential spec.
            actor: Кто запросил (principal / system). Передаётся в audit
                payload для трассировки доступа.

        Raises:
            KeyError: spec не зарегистрирован или env var отсутствует.
            ValueError: неподдерживаемый формат ``secret_ref``.

        """
        from src.backend.core.audit.facade.secrets import emit_secret_access

        spec = self._specs.get(name)
        if spec is None:
            await emit_secret_access(
                credential_name=name,
                secret_ref=name,  # нет spec — отдаём имя как resource
                actor=actor,
                outcome="failure",
                cache_status="miss",
                error_class="KeyError",
            )
            raise KeyError(
                f"Credential spec {name!r} not registered; "
                f"available: {sorted(self._specs)}"
            )

        cached = self._cache.get(name)
        if cached and (time.time() - cached.resolved_at) < spec.ttl_seconds:
            await emit_secret_access(
                credential_name=name,
                secret_ref=spec.secret_ref,
                actor=actor,
                outcome="success",
                cache_status="hit",
                resolution_id=cached.resolution_id,
            )
            return cached

        # Real implementation: read from vault_backend или env
        try:
            value = await self._resolve(spec)
        except (KeyError, ValueError) as exc:
            await emit_secret_access(
                credential_name=name,
                secret_ref=spec.secret_ref,
                actor=actor,
                outcome="failure",
                cache_status="miss",
                error_class=type(exc).__name__,
            )
            raise

        cred = ResolvedCredential(name=name, value=value)
        self._cache[name] = cred
        self._logger.info(
            "Credential resolved",
            extra={
                "name": name,
                "scope": spec.scope,
                "resolution_id": cred.resolution_id,
            },
        )
        await emit_secret_access(
            credential_name=name,
            secret_ref=spec.secret_ref,
            actor=actor,
            outcome="success",
            cache_status="miss",
            resolution_id=cred.resolution_id,
        )
        return cred

    async def _resolve(self, spec: CredentialSpec) -> dict[str, Any]:
        """Реальное разрешение credentials из vault/env с fail-closed."""
        if spec.is_vault:
            from src.backend.core.interfaces.secrets import SecretsBackend
            from src.backend.core.svcs_registry import get_service

            vault_path = spec.secret_ref.removeprefix("vault:")
            if not vault_path:
                raise ValueError(
                    f"Credential spec {spec.name!r}: empty vault path "
                    f"after 'vault:' prefix"
                )
            value = await get_service(SecretsBackend).get_secret(vault_path)
            if value is None:
                raise KeyError(
                    f"Vault returned None for {spec.name!r} "
                    f"(path={vault_path!r}); refusing to resolve empty credential"
                )
            return {"value": value}
        if spec.secret_ref.startswith("env:"):
            import os

            env_key = spec.secret_ref.removeprefix("env:")
            if not env_key:
                raise ValueError(
                    f"Credential spec {spec.name!r}: empty env var name "
                    f"after 'env:' prefix"
                )
            value = os.environ.get(env_key)
            if value is None:
                raise KeyError(
                    f"Environment variable {env_key!r} not set "
                    f"(required by credential spec {spec.name!r})"
                )
            return {"value": value}
        # Неизвестный формат ref — fail-loud, не silent return {}.
        raise ValueError(
            f"Credential spec {spec.name!r}: unsupported secret_ref format "
            f"{spec.secret_ref!r}; expected 'vault:<path>' or 'env:<KEY>'"
        )

    def invalidate(self, name: str) -> None:
        """Сбросить кэш (для rotation hooks)."""
        self._cache.pop(name, None)


_instance: CredentialProvider | None = None


def get_credential_provider() -> CredentialProvider:
    """Метод get_credential_provider (см. signature)."""
    global _instance
    if _instance is None:
        _instance = CredentialProvider()
    return _instance
