from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader


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
        json_schema_extra={"example": "minio"},
    )
    local_storage_path: Path = Field(
        default=Path("./dev_storage"),
        description=(
            "Путь к директории, используемой LocalFS-бэкендом, когда "
            "``provider=local``. Игнорируется при S3-совместимых провайдерах."
        ),
        json_schema_extra={"example": "./dev_storage"},
    )
    bucket: str = Field(
        default="my-bucket",
        description="Имя корзины по умолчанию",
        json_schema_extra={"example": "my-bucket"},
    )
    access_key: str = Field(
        "", description="Ключ доступа к хранилищу (пусто = anonymous)"
    )
    secret_key: str = Field(
        "", description="Секретный ключ (пусто = anonymous/public bucket)"
    )
    endpoint: str = Field(
        ...,
        description="URL API-эндпоинта хранилища",
        json_schema_extra={"example": "https://s3.example.com"},
    )
    interface_endpoint: str = Field(
        ...,
        description="URL веб-интерфейса хранилища",
        json_schema_extra={"example": "https://console.s3.example.com"},
    )

    # Параметры безопасности
    use_ssl: bool = Field(
        ...,
        description="Использовать HTTPS для подключений",
        json_schema_extra={"example": True},
    )
    verify: bool = Field(
        ...,
        description="Проверять SSL-сертификаты",
        json_schema_extra={"example": True},
    )
    ca_bundle: str | None = Field(
        default=None,
        description="Путь к пакету CA-сертификатов для SSL",
        json_schema_extra={"example": "/path/to/ca-bundle.crt"},
    )

    # Параметры производительности
    timeout: int = Field(
        ...,
        description="Таймаут операций (в секундах)",
        json_schema_extra={"example": 30},
    )
    retries: int = Field(
        ...,
        description="Количество попыток для неудачных операций",
        json_schema_extra={"example": 3},
    )
    max_pool_connections: int = Field(
        ...,
        description="Максимальное количество соединений в пуле",
        json_schema_extra={"example": 50},
    )
    read_timeout: int = Field(
        ...,
        description="Таймаут чтения объектов (в секундах)",
        json_schema_extra={"example": 30},
    )

    # Параметры ключей
    key_prefix: str = Field(
        ...,
        description="Префикс для ключей объектов",
        json_schema_extra={"example": "my-prefix/"},
    )

    @computed_field
    def normalized_endpoint(self) -> str:
        """Возвращает эндпоинт без схемы подключения (например, 'https://')."""
        return str(self.endpoint).split("://")[-1]

    def has_credentials(self) -> bool:
        """True, если заданы **оба** credential'а.

        Cycle 271 audit (HIGH-04): ``access_key``/``secret_key`` по умолчанию
        пусты и не объявлены ни в одном config-профиле — они приходят из
        переменных окружения на этапе деплоя. Отсутствие валидации означало,
        что опечатка в ``FS_ACCESS_KEY`` тихо превращала клиент в anonymous,
        и деплой при этом выглядел здоровым. Теперь это проверяемо явно.
        """
        return bool(self.access_key.strip()) and bool(self.secret_key.strip())

    def requires_credentials(self) -> bool:
        """True, если провайдеру действительно нужны credential'ы.

        Для ``provider=local`` (LocalFS) ключи не используются.
        """
        return self.provider != "local"

    # Безопасность хранения/раздачи (cycle 271, audit MEDIUM-02).
    server_side_encryption: str = Field(
        default="AES256",
        description=(
            "Алгоритм SSE для put_object (``AES256`` или ``aws:kms``). "
            "Пустая строка отключает серверное шифрование."
        ),
        json_schema_extra={"example": "AES256"},
    )
    presign_ttl_max_seconds: int = Field(
        default=604800,
        description=(
            "Потолок TTL для presigned-URL (7 дней по умолчанию). "
            "Запросы с ``expires_in`` выше потолка ограничиваются им и "
            "логируются: бессрочная ссылка на объект — вектор утечки."
        ),
        json_schema_extra={"example": 604800},
    )


fs_settings = FileStorageSettings()
"""Глобальные настройки файлового хранилища"""
