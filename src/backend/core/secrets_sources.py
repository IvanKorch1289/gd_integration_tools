"""Secrets management: Vault / AWS Secrets Manager sources для pydantic-settings.

Опциональные кастомные sources для Pydantic v2 settings.
Загружаются только если соответствующие библиотеки установлены
и соответствующие ENV vars заданы.

Usage в settings classes::

    from src.backend.core.secrets_sources import VaultSettingsSource

    class MySettings(BaseSettings):
        db_password: str
        api_key: str

        model_config = SettingsConfigDict(
            env_file=".env",
        )

        @classmethod
        def settings_customise_sources(cls, settings_cls, ...):
            return (
                init_settings,
                env_settings,
                VaultSettingsSource(settings_cls, "secret/myapp"),
                file_secret_settings,
            )
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("AwsSecretsManagerSource", "VaultSettingsSource")

logger = get_logger("core.secrets")


class VaultSettingsSource:
    """HashiCorp Vault secrets source for Pydantic settings.

    Reads from KV v2 secret engine. Требует ENV VAULT_ADDR + VAULT_TOKEN.
    """

    def __init__(self, settings_cls: type, secret_path: str) -> None:
        self._settings_cls = settings_cls
        self._secret_path = secret_path
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data

        import os

        addr = os.environ.get("VAULT_ADDR")
        token = os.environ.get("VAULT_TOKEN")
        if not (addr and token):
            self._data = {}
            return self._data

        try:
            import hvac
        except ImportError:
            logger.debug("hvac not installed, Vault source disabled")
            self._data = {}
            return self._data

        try:
            client = hvac.Client(url=addr, token=token)
            resp = client.secrets.kv.v2.read_secret_version(path=self._secret_path)
            self._data = resp.get("data", {}).get("data", {}) or {}
            logger.info(
                "Loaded %d secrets from Vault path %s",
                len(self._data),
                self._secret_path,
            )
        except Exception as exc:
            logger.warning("Vault load failed: %s", exc)
            self._data = {}

        return self._data

    def __call__(self) -> dict[str, Any]:
        return self._load()

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        """Получить значение секрета ``field_name`` из Vault KV v2.

        Args:
            field: Pydantic FieldInfo (используется для совместимости
                с pydantic-settings API; не читается).
            field_name: Имя ключа внутри JSON-секрета (например ``api_key``).

        Returns:
            Кортеж ``(value, field_name, is_complex)``: ``value`` равен
            ``None`` если ключ отсутствует; ``is_complex`` всегда ``False``
            (Vault source не помечает поля как complex).
        """
        data = self._load()
        if field_name in data:
            return data[field_name], field_name, False
        return None, field_name, False


class AwsSecretsManagerSource:
    """AWS Secrets Manager source for Pydantic settings.

    Requires ENV AWS_REGION. Use IAM role or access keys.
    Secret value must be JSON object with field names as keys.
    """

    def __init__(self, settings_cls: type, secret_name: str) -> None:
        self._settings_cls = settings_cls
        self._secret_name = secret_name
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data

        try:
            import boto3
            import orjson
        except ImportError:
            logger.debug("boto3 not installed, AWS Secrets source disabled")
            self._data = {}
            return self._data

        try:
            client = boto3.client("secretsmanager")
            resp = client.get_secret_value(SecretId=self._secret_name)
            secret_str = resp.get("SecretString", "{}")
            self._data = orjson.loads(secret_str) or {}
            logger.info(
                "Loaded %d secrets from AWS Secrets Manager %s",
                len(self._data),
                self._secret_name,
            )
        except Exception as exc:
            logger.warning("AWS Secrets Manager load failed: %s", exc)
            self._data = {}

        return self._data

    def __call__(self) -> dict[str, Any]:
        return self._load()

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        """Получить значение секрета ``field_name`` из AWS Secrets Manager.

        Args:
            field: Pydantic FieldInfo (для совместимости с pydantic-settings;
                не читается).
            field_name: Имя ключа внутри JSON-секрета (например ``db_password``).

        Returns:
            Кортеж ``(value, field_name, is_complex)``: ``value`` равен
            ``None`` если ключ отсутствует в секрете; ``is_complex`` всегда
            ``False``.
        """
        data = self._load()
        if field_name in data:
            return data[field_name], field_name, False
        return None, field_name, False
