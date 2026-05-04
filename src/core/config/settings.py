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
from src.core.config.dsl import DSLSettings, dsl_settings
from src.core.config.v11 import V11Settings, v11_settings
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
    InvokerSettings,
    LogStorageSettings,
    MailSettings,
    QueueSettings,
    RedisSettings,
    ResilienceSettings,
    SnapshotSettings,
    TaskiqSettings,
    TasksSettings,
    WatermarkSettings,
    cache_settings,
    fs_settings,
    grpc_settings,
    invoker_settings,
    log_settings,
    mail_settings,
    queue_settings,
    redis_settings,
    resilience_settings,
    snapshot_settings,
    taskiq_settings,
    tasks_settings,
    watermark_settings,
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

    # Invoker / TaskIQ (W22 F.2 C1-C3)
    invoker: InvokerSettings = invoker_settings
    taskiq: TaskiqSettings = taskiq_settings

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
    watermark: WatermarkSettings = watermark_settings

    # DSL hot-reload (W25)
    dsl: DSLSettings = dsl_settings

    # V11 R1.fin (ADR-042/043/044): PluginLoaderV11 + RouteLoader feature-flags.
    v11: V11Settings = v11_settings

    # Устойчивая инфраструктура (W26): per-service breaker-профили + fallback-политики
    resilience: ResilienceSettings = resilience_settings

    # PG → SQLite snapshot job (W26.8): incremental sync для resilience-fallback
    snapshot: SnapshotSettings = snapshot_settings


@lru_cache()
def get_app_settings() -> Settings:
    """Возвращает кэшированный экземпляр (Singleton) настроек приложения."""
    return Settings()


# Для обратной совместимости, если вам нужен глобальный объект где-то вне FastAPI
settings = get_app_settings()
