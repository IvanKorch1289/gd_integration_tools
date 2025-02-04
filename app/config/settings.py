from pydantic_settings import BaseSettings

from app.config.base import AppBaseSettings, app_base_settings
from app.config.database import (
    DatabaseConnectionSettings,
    db_connection_settings,
)
from app.config.outer_api import (
    DadataAPISettings,
    SKBAPISettings,
    dadata_api_settings,
    skb_api_settings,
)
from app.config.security import AuthSettings, auth_settings
from app.config.services import (
    CelerySettings,
    FileStorageSettings,
    LogStorageSettings,
    MailSettings,
    QueueSettings,
    RedisSettings,
    celery_settings,
    fs_settings,
    log_settings,
    mail_settings,
    queue_settings,
    redis_settings,
)


__all__ = ("settings",)


class Settings(BaseSettings):
    """Корневая конфигурация приложения.

    Объединяет все компоненты конфигурации:
    - Общие настройки приложения
    - Интеграции с внешними API
    - Настройки хранилищ данных
    - Системные компоненты
    """

    # Общие настройки
    app: AppBaseSettings = app_base_settings
    auth: AuthSettings = auth_settings

    # Интеграции
    database: DatabaseConnectionSettings = db_connection_settings
    skb_api: SKBAPISettings = skb_api_settings
    dadata_api: DadataAPISettings = dadata_api_settings
    queue: QueueSettings = queue_settings
    mail: MailSettings = mail_settings
    celery: CelerySettings = celery_settings

    # Хранилища
    storage: FileStorageSettings = fs_settings
    logging: LogStorageSettings = log_settings
    redis: RedisSettings = redis_settings


# Экземпляр настроек приложения
settings = Settings()
