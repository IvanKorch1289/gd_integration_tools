from functools import lru_cache

from pydantic_settings import BaseSettings

from src.core.config.ai import (
    AIProvidersSettings,
    NimSettings,
    OpenAISettings,
    OpenRouterSettings,
    ai_providers_settings,
    nim_settings,
    openai_settings,
    openrouter_settings,
)
from src.core.config.base import (
    AppBaseSettings,
    SchedulerSettings,
    app_base_settings,
    scheduler_settings,
)
from src.core.config.clickhouse import ClickHouseSettings, clickhouse_settings
from src.core.config.database import DatabaseConnectionSettings, db_connection_settings
from src.core.config.elasticsearch import ElasticsearchSettings, elasticsearch_settings
from src.core.config.express import ExpressSettings, express_settings
from src.core.config.external_apis import (
    AntivirusAPISettings,
    DadataAPISettings,
    SKBAPISettings,
    antivirus_api_settings,
    dadata_api_settings,
    skb_api_settings,
)
from src.core.config.external_databases import (
    ExternalDatabasesSettings,
    external_databases_settings,
)
from src.core.config.http_base import HttpBaseSettings, http_base_settings
from src.core.config.mongo import MongoConnectionSettings, mongo_connection_settings
from src.core.config.security import SecureSettings, secure_settings
from src.core.config.services import (
    CacheSettings,
    FileStorageSettings,
    GRPCSettings,
    LogStorageSettings,
    MailSettings,
    QueueSettings,
    RedisSettings,
    TasksSettings,
    cache_settings,
    fs_settings,
    grpc_settings,
    log_settings,
    mail_settings,
    queue_settings,
    redis_settings,
    tasks_settings,
)
from src.core.config.telegram import TelegramBotSettings, telegram_bot_settings
from src.core.config.vault import VaultSettings, vault_settings

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
    vault: VaultSettings = vault_settings

    # Интеграции
    antivirus: AntivirusAPISettings = antivirus_api_settings
    database: DatabaseConnectionSettings = db_connection_settings
    external_databases: ExternalDatabasesSettings = external_databases_settings
    skb_api: SKBAPISettings = skb_api_settings
    dadata_api: DadataAPISettings = dadata_api_settings
    queue: QueueSettings = queue_settings
    mail: MailSettings = mail_settings
    tasks: TasksSettings = tasks_settings
    grpc: GRPCSettings = grpc_settings

    # Аналитика / поиск
    clickhouse: ClickHouseSettings = clickhouse_settings
    express: ExpressSettings = express_settings
    telegram: TelegramBotSettings = telegram_bot_settings
    elasticsearch: ElasticsearchSettings = elasticsearch_settings

    # AI-провайдеры
    ai_providers: AIProvidersSettings = ai_providers_settings
    openrouter: OpenRouterSettings = openrouter_settings
    nim: NimSettings = nim_settings
    openai: OpenAISettings = openai_settings

    # Хранилища
    storage: FileStorageSettings = fs_settings
    logging: LogStorageSettings = log_settings
    redis: RedisSettings = redis_settings
    mongo: MongoConnectionSettings = mongo_connection_settings
    cache: CacheSettings = cache_settings


@lru_cache()
def get_app_settings() -> Settings:
    """Возвращает кэшированный экземпляр (Singleton) настроек приложения."""
    return Settings()


# Для обратной совместимости, если вам нужен глобальный объект где-то вне FastAPI
settings = get_app_settings()
