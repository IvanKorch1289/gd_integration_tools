from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader


class FileStorageSettings(BaseSettingsWithLoader):
    """Настройки для подключения к S3-совместимому объектному хранилищу."""

    yaml_group: ClassVar[str] = "fs"
    model_config = SettingsConfigDict(env_prefix="FS_", extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "Включить S3-совместимый бэкенд при старте. Для dev_light "
            "достаточно ``provider=local`` (LocalFS), s3-клиент пропускается."
        ),
    )

    # Основные параметры подключения
    provider: Literal["minio", "aws", "other", "local"] = Field(
        ...,
        description=(
            "Тип провайдера хранилища. ``local`` — LocalFS бэкенд для dev-стенда "
            "(не использовать в production)."
        ),
        example="minio",
    )
    local_storage_path: Path = Field(
        default=Path("./dev_storage"),
        description=(
            "Путь к директории, используемой LocalFS-бэкендом, когда "
            "``provider=local``. Игнорируется при S3-совместимых провайдерах."
        ),
        example="./dev_storage",
    )
    bucket: str = Field(
        default="my-bucket",
        env="FS_BUCKET",
        description="Имя корзины по умолчанию",
        example="my-bucket",
    )
    access_key: str = Field(..., description="Ключ доступа к хранилищу")
    secret_key: str = Field(..., description="Секретный ключ доступа к хранилищу")
    endpoint: str = Field(
        ..., description="URL API-эндпоинта хранилища", example="https://s3.example.com"
    )
    interface_endpoint: str = Field(
        ...,
        description="URL веб-интерфейса хранилища",
        example="https://console.s3.example.com",
    )

    # Параметры безопасности
    use_ssl: bool = Field(
        ..., description="Использовать HTTPS для подключений", example=True
    )
    verify: bool = Field(..., description="Проверять SSL-сертификаты", example=True)
    ca_bundle: str | None = Field(
        default=None,
        env="FS_CA_BUNDLE",
        description="Путь к пакету CA-сертификатов для SSL",
        example="/path/to/ca-bundle.crt",
    )

    # Параметры производительности
    timeout: int = Field(..., description="Таймаут операций (в секундах)", example=30)
    retries: int = Field(
        ..., description="Количество попыток для неудачных операций", example=3
    )
    max_pool_connections: int = Field(
        ..., description="Максимальное количество соединений в пуле", example=50
    )
    read_timeout: int = Field(
        ..., description="Таймаут чтения объектов (в секундах)", example=30
    )

    # Параметры ключей
    key_prefix: str = Field(
        ..., description="Префикс для ключей объектов", example="my-prefix/"
    )

    @computed_field
    def normalized_endpoint(self) -> str:
        """Возвращает эндпоинт без схемы подключения (например, 'https://')."""
        return str(self.endpoint).split("://")[-1]


fs_settings = FileStorageSettings()
"""Глобальные настройки файлового хранилища"""
