from functools import lru_cache

from pydantic_settings import BaseSettings

from app.core.config.base import (
    AppBaseSettings,
    SchedulerSettings,
    app_base_settings,
    scheduler_settings,
)
from app.core.config.database import (
    DatabaseConnectionSettings,
    MongoConnectionSettings,
    db_connection_settings,
    mongo_connection_settings,
)
from app.core.config.external_databases import (
    ExternalDatabasesSettings,
    external_databases_settings,
)
from app.core.config.antivirus_api import AntivirusAPISettings, antivirus_api_settings
from app.core.config.dadata_api import DadataAPISettings, dadata_api_settings
from app.core.config.http_base import HttpBaseSettings, http_base_settings
from app.core.config.skb_api import SKBAPISettings, skb_api_settings
from app.core.config.clickhouse import ClickHouseSettings, clickhouse_settings
from app.core.config.express_settings import ExpressSettings, express_settings
from app.core.config.elasticsearch import ElasticsearchSettings, elasticsearch_settings
from app.core.config.security import SecureSettings, secure_settings
from app.core.config.services import (
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

__all__ = ("Settings", "settings")


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
    antivirus: AntivirusAPISettings = antivirus_api_settings
    database: DatabaseConnectionSettings = db_connection_settings
    external_databases: ExternalDatabasesSettings = external_databases_settings
    skb_api: SKBAPISettings = skb_api_settings
    dadata_api: DadataAPISettings = dadata_api_settings
    queue: QueueSettings = queue_settings
    mail: MailSettings = mail_settings
    celery: CelerySettings = celery_settings
    tasks: TasksSettings = tasks_settings
    grpc: GRPCSettings = grpc_settings

    # Аналитика / поиск
    clickhouse: ClickHouseSettings = clickhouse_settings
    express: ExpressSettings = express_settings
    elasticsearch: ElasticsearchSettings = elasticsearch_settings

    # Хранилища
    storage: FileStorageSettings = fs_settings
    logging: LogStorageSettings = log_settings
    redis: RedisSettings = redis_settings
    mongo: MongoConnectionSettings = mongo_connection_settings


@lru_cache()
def get_app_settings() -> Settings:
    """Возвращает кэшированный экземпляр (Singleton) настроек приложения."""
    return Settings()


# Для обратной совместимости, если вам нужен глобальный объект где-то вне FastAPI
settings = get_app_settings()
