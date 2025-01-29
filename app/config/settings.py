from pydantic_settings import BaseSettings

from app.config.base import AppBaseSettings
from app.config.database import DatabaseSettings
from app.config.outer_api import APIDADATASettings, APISSKBSettings
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
    app: AppBaseSettings = AppBaseSettings()
    auth: AuthSettings = AuthSettings()

    # Интеграции
    database: DatabaseSettings = DatabaseSettings()
    skb_api: APISSKBSettings = APISSKBSettings()
    dadata_api: APIDADATASettings = APIDADATASettings()
    queue: QueueSettings = QueueSettings()
    mail: MailSettings = MailSettings()
    celery: CelerySettings = CelerySettings()

    # Хранилища
    storage: FileStorageSettings = FileStorageSettings()
    logging: LogStorageSettings = LogStorageSettings()
    redis: RedisSettings = RedisSettings()


# Экземпляр настроек приложения
settings = Settings()
