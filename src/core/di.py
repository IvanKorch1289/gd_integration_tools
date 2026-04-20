"""Dependency Injection — централизованная регистрация компонентов через app.state.

Все singletons инициализируются в ``register_app_state`` при старте приложения
и доступны через ``Depends(get_xxx)`` в FastAPI-эндпоинтах.

Для non-FastAPI контекстов (Prefect, scripts, DSL engine) каждый модуль
использует ``app_state_singleton`` — декоратор, который устраняет дублирование
15× одинаковых get_xxx() функций.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

from fastapi import Request

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.core.config.vault_refresher import VaultSecretRefresher
    from app.core.security.api_key_manager import APIKeyManager
    from app.dsl.engine.plugin_registry import ProcessorPluginRegistry
    from app.dsl.engine.tracer import ExecutionTracer
    from app.dsl.engine.versioning import PipelineVersionManager
    from app.entrypoints.mqtt.mqtt_handler import MqttHandler
    from app.infrastructure.application.slo_tracker import SLOTracker
    from app.infrastructure.clients.messaging.kafka import KafkaClient
    from app.infrastructure.clients.external.langfuse_client import LangFuseClient
    from app.infrastructure.database.pool_monitor import PoolMonitor

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

_app_ref: FastAPI | None = None


def register_app_state(app: FastAPI) -> None:
    """Инициализирует все singletons и сохраняет в app.state."""
    global _app_ref
    _app_ref = app

    from app.core.security.api_key_manager import APIKeyManager
    from app.dsl.engine.plugin_registry import ProcessorPluginRegistry
    from app.dsl.engine.tracer import ExecutionTracer
    from app.dsl.engine.versioning import PipelineVersionManager
    from app.infrastructure.application.slo_tracker import SLOTracker
    from app.infrastructure.clients.messaging.kafka import KafkaClient
    from app.infrastructure.clients.external.langfuse_client import LangFuseClient
    from app.infrastructure.database.pool_monitor import PoolMonitor

    app.state.api_key_manager = APIKeyManager()
    app.state.tracer = ExecutionTracer()
    app.state.plugin_registry = ProcessorPluginRegistry()
    app.state.pipeline_version_manager = PipelineVersionManager()
    app.state.slo_tracker = SLOTracker()
    app.state.kafka_client = KafkaClient()
    app.state.pool_monitor = PoolMonitor()
    app.state.langfuse_client = LangFuseClient()

    from app.core.config.vault_refresher import VaultSecretRefresher

    app.state.vault_refresher = VaultSecretRefresher()

    from app.entrypoints.mqtt.mqtt_handler import MqttHandler, MqttSettings

    try:
        mqtt_settings = MqttSettings()
    except Exception:
        mqtt_settings = MqttSettings(
            broker_host="localhost", broker_port=1883, enabled=False
        )
    app.state.mqtt_handler = MqttHandler(mqtt_settings)


def _get_from_app_state(attr: str) -> Any:
    if _app_ref is not None:
        return getattr(_app_ref.state, attr, None)
    return None


def app_state_singleton(
    attr: str,
    factory: Callable[[], T] | None = None,
) -> Callable[[], T]:
    """Декоратор-фабрика: убирает 15× дублированный паттерн get_xxx().

    Сначала ищет в app.state, потом lazy-init через factory.

    Usage::

        @app_state_singleton("clickhouse_client", lambda: ClickHouseClient(...))
        def get_clickhouse_client() -> ClickHouseClient: ...

    Или без factory (для no-arg конструкторов, инициализированных в register_app_state)::

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


# --- FastAPI Depends functions (for endpoint injection) ---


async def get_api_key_manager(request: Request) -> APIKeyManager:
    return request.app.state.api_key_manager


async def get_tracer(request: Request) -> ExecutionTracer:
    return request.app.state.tracer


async def get_plugin_registry(request: Request) -> ProcessorPluginRegistry:
    return request.app.state.plugin_registry


async def get_pipeline_version_manager(request: Request) -> PipelineVersionManager:
    return request.app.state.pipeline_version_manager


async def get_slo_tracker(request: Request) -> SLOTracker:
    return request.app.state.slo_tracker


async def get_kafka_client(request: Request) -> KafkaClient:
    return request.app.state.kafka_client


async def get_pool_monitor(request: Request) -> PoolMonitor:
    return request.app.state.pool_monitor


async def get_vault_refresher(request: Request) -> VaultSecretRefresher:
    return request.app.state.vault_refresher


async def get_mqtt_handler(request: Request) -> MqttHandler:
    return request.app.state.mqtt_handler


async def get_langfuse_client(request: Request) -> LangFuseClient:
    return request.app.state.langfuse_client
