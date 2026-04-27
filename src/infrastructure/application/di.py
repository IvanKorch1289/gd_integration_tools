"""
Композиционный корень приложения: регистрация всех singleton-сервисов в app.state.

Единственное место в проекте, где concrete-реализации из нижележащих слоёв
(infrastructure.security, dsl, infrastructure.*) импортируются и
привязываются к FastAPI через ``app.state.*``. Располагается в
infrastructure/application/ согласно Clean Architecture — composition root
принадлежит внешнему слою.

Все singletons инициализируются в ``register_app_state`` при старте
приложения и доступны через ``Depends(get_xxx)`` в FastAPI-эндпоинтах.

Для non-FastAPI контекстов (Prefect, scripts, DSL engine) каждый модуль
использует ``app_state_singleton`` — декоратор-фабрику, устраняющий
дублирование ``get_xxx()`` функций.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

from fastapi import Request

if TYPE_CHECKING:
    from fastapi import FastAPI

    from src.dsl.engine.plugin_registry import ProcessorPluginRegistry
    from src.dsl.engine.tracer import ExecutionTracer
    from src.dsl.engine.versioning import PipelineVersionManager
    from src.entrypoints.mqtt.mqtt_handler import MqttHandler
    from src.infrastructure.application.slo_tracker import SLOTracker
    from src.infrastructure.application.vault_refresher import VaultSecretRefresher
    from src.infrastructure.clients.external.langfuse_client import LangFuseClient
    from src.infrastructure.clients.messaging.kafka import KafkaClient
    from src.infrastructure.database.pool_monitor import PoolMonitor
    from src.infrastructure.security.api_key_manager import APIKeyManager

T = TypeVar("T")

__all__ = (
    "register_app_state",
    "app_state_singleton",
    "_get_from_app_state",
    "get_api_key_manager",
    "get_tracer",
    "get_plugin_registry",
    "get_pipeline_version_manager",
    "get_slo_tracker",
    "get_kafka_client",
    "get_pool_monitor",
    "get_vault_refresher",
    "get_mqtt_handler",
    "get_langfuse_client",
)

# Ссылка на FastAPI-приложение, сохраняется при первой инициализации
# и используется в non-request контекстах (Prefect workers, CLI).
_app_ref: FastAPI | None = None


def register_app_state(app: FastAPI) -> None:
    """
    Инициализирует все singletons приложения и кладёт их в ``app.state``.

    Вызывается один раз в lifespan при старте. Импорты concrete-классов
    делаются lazy (внутри функции), чтобы избежать cycle и уменьшить
    время холодного старта.

    Args:
        app: Экземпляр FastAPI для записи singletons в ``app.state``.
    """
    global _app_ref
    _app_ref = app

    from src.dsl.engine.plugin_registry import ProcessorPluginRegistry
    from src.dsl.engine.tracer import ExecutionTracer
    from src.dsl.engine.versioning import PipelineVersionManager
    from src.infrastructure.application.slo_tracker import SLOTracker
    from src.infrastructure.clients.external.langfuse_client import LangFuseClient
    from src.infrastructure.clients.messaging.kafka import KafkaClient
    from src.infrastructure.database.pool_monitor import PoolMonitor
    from src.infrastructure.security.api_key_manager import APIKeyManager

    app.state.api_key_manager = APIKeyManager()
    app.state.tracer = ExecutionTracer()
    app.state.plugin_registry = ProcessorPluginRegistry()
    app.state.pipeline_version_manager = PipelineVersionManager()
    app.state.slo_tracker = SLOTracker()
    app.state.kafka_client = KafkaClient()
    app.state.pool_monitor = PoolMonitor()
    app.state.langfuse_client = LangFuseClient()

    from src.infrastructure.application.vault_refresher import VaultSecretRefresher

    app.state.vault_refresher = VaultSecretRefresher()

    from src.entrypoints.mqtt.mqtt_handler import MqttHandler, MqttSettings

    try:
        mqtt_settings = MqttSettings()
    except Exception:
        # Fallback на локальный брокер, если конфиг невалиден в dev-окружении.
        mqtt_settings = MqttSettings(
            broker_host="localhost", broker_port=1883, enabled=False
        )
    app.state.mqtt_handler = MqttHandler(mqtt_settings)


def _get_from_app_state(attr: str) -> Any:
    """
    Возвращает атрибут из ``app.state`` или ``None`` если приложение не создано.

    Args:
        attr: Имя атрибута в ``app.state``.

    Returns:
        Значение атрибута либо ``None`` если app ещё не инициализирован
        или атрибут отсутствует.
    """
    if _app_ref is not None:
        return getattr(_app_ref.state, attr, None)
    return None


def app_state_singleton(
    attr: str, factory: Callable[[], T] | None = None
) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """
    Декоратор-фабрика singleton-доступа к объектам из ``app.state``.

    Убирает 15× дублированный паттерн ``def get_xxx(): return app.state.xxx``.
    Сначала ищет объект в ``app.state``, затем lazy-init через factory
    (для контекстов без FastAPI).

    Args:
        attr: Имя атрибута в ``app.state``.
        factory: Опциональная фабрика для lazy-init в non-request контекстах.

    Returns:
        Декоратор, превращающий функцию-заглушку в accessor singleton'а.

    Пример::

        @app_state_singleton("clickhouse_client", lambda: ClickHouseClient(...))
        def get_clickhouse_client() -> ClickHouseClient: ...

        @app_state_singleton("tracer")
        def get_tracer() -> ExecutionTracer: ...
    """
    _cache: dict[str, Any] = {}

    def decorator(fn: Callable[[], T]) -> Callable[[], T]:
        def wrapper() -> T:
            instance = _get_from_app_state(attr)
            if instance is not None:
                return instance
            if attr not in _cache:
                if factory is not None:
                    _cache[attr] = factory()
                else:
                    raise RuntimeError(
                        f"{attr} not in app.state and no factory provided. "
                        "Ensure register_app_state() was called."
                    )
            return _cache[attr]

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__qualname__ = fn.__qualname__
        return wrapper

    return decorator


# --- FastAPI Depends-функции для инъекции singletons в эндпоинты ---


async def get_api_key_manager(request: Request) -> APIKeyManager:
    """Возвращает APIKeyManager из app.state (FastAPI Depends)."""
    return request.app.state.api_key_manager


async def get_tracer(request: Request) -> ExecutionTracer:
    """Возвращает ExecutionTracer из app.state (FastAPI Depends)."""
    return request.app.state.tracer


async def get_plugin_registry(request: Request) -> ProcessorPluginRegistry:
    """Возвращает ProcessorPluginRegistry из app.state (FastAPI Depends)."""
    return request.app.state.plugin_registry


async def get_pipeline_version_manager(request: Request) -> PipelineVersionManager:
    """Возвращает PipelineVersionManager из app.state (FastAPI Depends)."""
    return request.app.state.pipeline_version_manager


async def get_slo_tracker(request: Request) -> SLOTracker:
    """Возвращает SLOTracker из app.state (FastAPI Depends)."""
    return request.app.state.slo_tracker


async def get_kafka_client(request: Request) -> KafkaClient:
    """Возвращает KafkaClient из app.state (FastAPI Depends)."""
    return request.app.state.kafka_client


async def get_pool_monitor(request: Request) -> PoolMonitor:
    """Возвращает PoolMonitor из app.state (FastAPI Depends)."""
    return request.app.state.pool_monitor


async def get_vault_refresher(request: Request) -> VaultSecretRefresher:
    """Возвращает VaultSecretRefresher из app.state (FastAPI Depends)."""
    return request.app.state.vault_refresher


async def get_mqtt_handler(request: Request) -> MqttHandler:
    """Возвращает MqttHandler из app.state (FastAPI Depends)."""
    return request.app.state.mqtt_handler


async def get_langfuse_client(request: Request) -> LangFuseClient:
    """Возвращает LangFuseClient из app.state (FastAPI Depends)."""
    return request.app.state.langfuse_client
