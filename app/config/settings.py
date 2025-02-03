from pydantic_settings import BaseSettings

from app.config.base import AppBaseSettings, app_base_settings
from app.config.database import DatabaseSettings, db_connection_settings
from app.config.outer_api import (
    APIDADATASettings,
    APISSKBSettings,
    dadata_api_settings,
    skb_api_settings,
)
from app.config.security import AuthSettings
from app.config.services import (
    CelerySettings,
    FileStorageSettings,
    LogStorageSettings,
    MailSettings,
    QueueSettings,
    RedisSettings,
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
    auth: AuthSettings = AuthSettings()

    # Интеграции
    database: DatabaseSettings = db_connection_settings
    skb_api: APISSKBSettings = skb_api_settings
    dadata_api: APIDADATASettings = dadata_api_settings
    queue: QueueSettings = QueueSettings()
    mail: MailSettings = MailSettings()
    celery: CelerySettings = CelerySettings()

    # Хранилища
    storage: FileStorageSettings = FileStorageSettings()
    logging: LogStorageSettings = LogStorageSettings()
    redis: RedisSettings = RedisSettings()


# Экземпляр настроек приложения
settings = Settings()
