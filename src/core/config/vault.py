"""Конфигурация HashiCorp Vault (KV v2).

Поле ``enabled`` — основной переключатель источника секретов; читается
loader-ом до загрузки остальных Settings-классов через
``_is_vault_enabled`` (см. ``src.core.config.config_loader``). Остальные
поля (``addr``/``token``/``secret_path``) — зеркало env-переменных
``VAULT_*``, фактически читаемых ``vault_refresher``/``vault_cipher``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("VaultSettings", "vault_settings")


class VaultSettings(BaseSettingsWithLoader):
    """Конфигурация подключения к Vault."""

    yaml_group: ClassVar[str] = "vault"
    model_config = SettingsConfigDict(env_prefix="VAULT_", extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Включить чтение секретов из Vault.",
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
    addr: str = Field(
        default="",
        description="URL Vault-сервера (env VAULT_ADDR).",
    )
    token: str = Field(
        default="",
        description="Токен авторизации (env VAULT_TOKEN).",
    )
    secret_path: str = Field(
        default="",
        description="Путь KV v2 к секретам (env VAULT_SECRET_PATH).",
    )


vault_settings = VaultSettings()
"""Глобальный экземпляр настроек Vault."""
