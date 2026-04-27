"""Настройки CertStore (Wave 2.1).

Бэкенды:

* ``vault`` — HashiCorp Vault KV v2 (prod, рекомендованный);
* ``postgres`` — таблица ``certs`` (PostgreSQL, fallback при недоступности Vault);
* ``memory`` — in-process dict (только для unit-тестов).

В Redis допустим только short-TTL кэш fingerprint (НЕ PEM).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("CertStoreSettings", "cert_store_settings")


class CertStoreSettings(BaseSettingsWithLoader):
    """Конфигурация хранилища TLS-сертификатов."""

    yaml_group: ClassVar[str] = "cert_store"
    model_config = SettingsConfigDict(env_prefix="CERT_STORE_", extra="forbid")

    backend: Literal["vault", "postgres", "memory"] = Field(
        default="postgres",
        description="Бэкенд хранения сертификатов.",
        examples=["postgres", "vault", "memory"],
    )
    hot_cache_ttl: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="TTL Redis-кэша fingerprint в секундах (НЕ PEM).",
        examples=[300, 60],
    )
    vault_path: str = Field(
        default="secret/certs",
        description="Базовый путь в Vault KV v2 для хранения PEM.",
        examples=["secret/certs", "kv/data/certs"],
    )
    expire_warn_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description=(
            "Окно в днях, при котором сертификат считается «истекающим» "
            "и попадает в ``get_expiring_soon()``."
        ),
        examples=[30, 14],
    )


cert_store_settings = CertStoreSettings()
"""Глобальный экземпляр настроек CertStore."""
