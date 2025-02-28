from pydantic_settings import BaseSettings

from app.config.base import (
    AppBaseSettings,
    SchedulerSettings,
    app_base_settings,
    scheduler_settings,
)
from app.config.database import (
    DatabaseConnectionSettings,
    MongoConnectionSettings,
    db_connection_settings,
    mongo_connection_settings,
)
from app.config.outer_api import (
    DadataAPISettings,
    HttpBaseSettings,
    SKBAPISettings,
    dadata_api_settings,
    http_base_settings,
    skb_api_settings,
)
from app.config.security import SecureSettings, secure_settings
from app.config.services import (
    CelerySettings,
    FileStorageSettings,
    GRPCSettings,
    LogStorageSettings,
    MailSettings,
    QueueSettings,
    RedisSettings,
    TasksSettings,
    celery_settings,
    fs_settings,
    grpc_settings,
    log_settings,
    mail_settings,
    queue_settings,
    redis_settings,
    tasks_settings,
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
    secure: SecureSettings = secure_settings
    http_base_settings: HttpBaseSettings = http_base_settings
    scheduler: SchedulerSettings = scheduler_settings

    # Интеграции
    database: DatabaseConnectionSettings = db_connection_settings
    skb_api: SKBAPISettings = skb_api_settings
    dadata_api: DadataAPISettings = dadata_api_settings
    queue: QueueSettings = queue_settings
    mail: MailSettings = mail_settings
    celery: CelerySettings = celery_settings
    tasks: TasksSettings = tasks_settings
    grpc: GRPCSettings = grpc_settings

    # Хранилища
    storage: FileStorageSettings = fs_settings
    logging: LogStorageSettings = log_settings
    redis: RedisSettings = redis_settings
    mongo: MongoConnectionSettings = mongo_connection_settings


# Экземпляр настроек приложения
settings = Settings()
