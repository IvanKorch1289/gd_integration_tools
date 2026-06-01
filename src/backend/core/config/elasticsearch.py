"""Настройки подключения к Elasticsearch."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("ElasticsearchSettings", "elasticsearch_settings")


class ElasticsearchSettings(BaseSettingsWithLoader):
    """Конфигурация подключения к Elasticsearch."""

    yaml_group: ClassVar[str] = "elasticsearch"
    model_config = SettingsConfigDict(env_prefix="ES_", extra="forbid")

    hosts: list[str] = Field(
        default_factory=lambda: ["http://localhost:9200"],
        description="Список URL-ов узлов ES.",
    )
    api_key: str | None = Field(None, description="API key для аутентификации.")
    username: str | None = Field(None, description="Имя пользователя (basic auth).")
    password: str | None = Field(None, description="Пароль (basic auth).")
    verify_certs: bool = Field(True, description="Проверять TLS-сертификаты.")
    ca_certs: str | None = Field(None, description="Путь к CA-сертификату.")
    request_timeout: int = Field(30, ge=1, description="Таймаут запроса (сек).")
    max_retries: int = Field(3, ge=0, description="Кол-во повторов при ошибке.")
    index_prefix: str = Field("gd_", description="Префикс индексов.")
    enabled: bool = Field(False, description="Включить Elasticsearch интеграцию.")


elasticsearch_settings = ElasticsearchSettings()
