"""Конфигурация HashiCorp Vault (KV v2).

Поле ``enabled`` — основной переключатель источника секретов; читается
loader-ом до загрузки остальных Settings-классов через
``_is_vault_enabled`` (см. ``src.core.config.config_loader``). Остальные
поля (``addr``/``token``/``secret_path``) — зеркало env-переменных
``VAULT_*``, фактически читаемых ``vault_refresher``/``vault_cipher``.

ADR-0376: ``vault_endpoint()``/``vault_secret_path()`` — единая точка
разрешения адреса и пути Vault для ВСЕХ потребителей (refresher, secrets
chain, backend, PKI, SSO). Раньше потребители читали только ``os.environ``
и игнорировали YAML-секцию ``vault`` (ADR-0372 перенёс ``VAULT_ADDR``/
``VAULT_SECRET_PATH`` в ``config_profiles/*.yml``) — в окружении без
env-переменной Vault был «не сконфигурирован» даже при заданном YAML.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import (
    BaseSettingsWithLoader,
    env_lookup,
    vault_yaml_config,
)

__all__ = (
    "VaultSettings",
    "vault_endpoint",
    "vault_secret_path",
    "vault_settings",
)


def vault_endpoint() -> str:
    """URL Vault-сервера (единая точка разрешения для потребителей).

    Приоритет (ADR-0372 §5, продолжается в ADR-0376):

    1. реальное окружение (``VAULT_ADDR``, не значение из ``.env``);
    2. YAML-секция ``vault.addr`` (``config_profiles/*.yml``);
    3. ``.env`` (последний fallback).

    Returns:
        Адрес Vault-сервера (пустая строка — если не задан).

    """
    env_addr = env_lookup("VAULT_ADDR")
    if env_addr:
        return env_addr.strip()
    yaml_addr = str(vault_yaml_config().get("addr") or "").strip()
    if yaml_addr:
        return yaml_addr
    return os.environ.get("VAULT_ADDR", "").strip()


def vault_secret_path() -> str:
    """Путь KV v2 к секретам (единая точка разрешения для потребителей).

    Приоритет тот же, что в :func:`vault_endpoint`: реальное окружение →
    YAML (``vault.secret_path``) → ``.env``.

    Returns:
        Путь к секрету (пустая строка — если не задан).

    """
    env_path = env_lookup("VAULT_SECRET_PATH")
    if env_path:
        return env_path.strip()
    yaml_path = str(vault_yaml_config().get("secret_path") or "").strip()
    if yaml_path:
        return yaml_path
    return os.environ.get("VAULT_SECRET_PATH", "").strip()


class VaultSettings(BaseSettingsWithLoader):
    """Конфигурация подключения к Vault."""

    yaml_group: ClassVar[str] = "vault"
    model_config = SettingsConfigDict(env_prefix="VAULT_", extra="forbid")

    enabled: bool = Field(
        default=True, description="Включить чтение секретов из Vault."
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _coerce_enabled(cls, value: Any) -> Any:
        """Принимает пустой ``VAULT_ENABLED=`` как ``True`` (default).

        Pydantic строгий по парсингу bool: пустая строка из env вызывает
        ValidationError. Считаем пустую строку отсутствием override —
        что согласуется с ``_is_vault_enabled`` в ``config_loader``.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return True
            if stripped.lower() in {"0", "false", "no"}:
                return False
            if stripped.lower() in {"1", "true", "yes"}:
                return True
        return value

    addr: str = Field(default="", description="URL Vault-сервера (env VAULT_ADDR).")
    token: str = Field(default="", description="Токен авторизации (env VAULT_TOKEN).")
    secret_path: str = Field(
        default="", description="Путь KV v2 к секретам (env VAULT_SECRET_PATH)."
    )


vault_settings = VaultSettings()
"""Глобальный экземпляр настроек Vault."""
