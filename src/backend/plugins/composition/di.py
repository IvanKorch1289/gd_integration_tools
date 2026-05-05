"""
Композиционный корень приложения: регистрация всех singleton-сервисов в app.state.

Единственное место в проекте, где concrete-реализации из нижележащих слоёв
(infrastructure.security, dsl, infrastructure.*) импортируются и
привязываются к FastAPI через ``app.state.*``. Располагается в
infrastructure/application/ согласно Clean Architecture — composition root
принадлежит внешнему слою.

Все singletons инициализируются в ``register_app_state`` при старте
приложения и доступны через ``Depends(get_xxx)`` в FastAPI-эндпоинтах.

Для non-FastAPI контекстов (CLI scripts, DSL engine, durable workflow runner)
каждый модуль использует ``app_state_singleton`` — декоратор-фабрику,
устраняющий дублирование ``get_xxx()`` функций.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from src.backend.core.di import app_state_singleton, set_app_ref
from src.backend.core.di.app_state import _get_from_app_state

if TYPE_CHECKING:
    from fastapi import FastAPI

    from src.backend.core.interfaces.watermark_store import WatermarkStore
    from src.backend.dsl.engine.plugin_registry import ProcessorPluginRegistry
    from src.backend.dsl.engine.tracer import ExecutionTracer
    from src.backend.dsl.engine.versioning import PipelineVersionManager
    from src.backend.entrypoints.mqtt.mqtt_handler import MqttHandler
    from src.backend.infrastructure.application.slo_tracker import SLOTracker
    from src.backend.infrastructure.application.vault_refresher import (
        VaultSecretRefresher,
    )
    from src.backend.infrastructure.clients.external.langfuse_client import (
        LangFuseClient,
    )
    from src.backend.infrastructure.database.pool_monitor import PoolMonitor
    from src.backend.infrastructure.security.api_key_manager import APIKeyManager

__all__ = (
    "register_app_state",
    "app_state_singleton",
    "_get_from_app_state",
    "get_api_key_manager",
    "get_tracer",
    "get_plugin_registry",
    "get_pipeline_version_manager",
    "get_slo_tracker",
    "get_pool_monitor",
    "get_vault_refresher",
    "get_mqtt_handler",
    "get_langfuse_client",
    "get_watermark_store",
)


def register_app_state(app: FastAPI) -> None:
    """
    Инициализирует все singletons приложения и кладёт их в ``app.state``.

    Вызывается один раз в lifespan при старте. Импорты concrete-классов
    делаются lazy (внутри функции), чтобы избежать cycle и уменьшить
    время холодного старта.

    Args:
        app: Экземпляр FastAPI для записи singletons в ``app.state``.
    """
    set_app_ref(app)

    from src.backend.dsl.engine.plugin_registry import ProcessorPluginRegistry
    from src.backend.dsl.engine.tracer import ExecutionTracer
    from src.backend.dsl.engine.versioning import PipelineVersionManager
    from src.backend.infrastructure.application.slo_tracker import SLOTracker
    from src.backend.infrastructure.clients.external.langfuse_client import (
        LangFuseClient,
    )
    from src.backend.infrastructure.database.pool_monitor import PoolMonitor
    from src.backend.infrastructure.security.api_key_manager import APIKeyManager

    app.state.api_key_manager = APIKeyManager()
    app.state.tracer = ExecutionTracer()
    app.state.plugin_registry = ProcessorPluginRegistry()
    app.state.pipeline_version_manager = PipelineVersionManager()
    app.state.slo_tracker = SLOTracker()
    app.state.pool_monitor = PoolMonitor()
    app.state.langfuse_client = LangFuseClient()

    # W22 техдолг: composition root для Invoker + ReplyChannelRegistry.
    # Concrete реализация регистрируется здесь, чтобы services/execution
    # и entrypoints зависели только от Protocol через core/di.dependencies.
    from src.backend.infrastructure.messaging.invocation_replies import (
        get_reply_channel_registry,
    )
    from src.backend.services.execution.invoker import Invoker

    app.state.reply_registry = get_reply_channel_registry()
    app.state.invoker = Invoker()

    from src.backend.infrastructure.application.vault_refresher import (
        VaultSecretRefresher,
    )

    app.state.vault_refresher = VaultSecretRefresher()

    # W14.5: durable WatermarkStore — выбор бэкенда (memory/postgres) по
    # ``WatermarkSettings``. PG-вариант берёт главный session_manager;
    # memory не требует БД и пригоден для dev_light/тестов.
    from src.backend.core.config.services.watermark import (
        watermark_settings as _watermark_settings,
    )
    from src.backend.infrastructure.database.session_manager import main_session_manager
    from src.backend.infrastructure.watermark.factory import create_watermark_store

    app.state.watermark_store = create_watermark_store(
        _watermark_settings, session_manager=main_session_manager
    )

    from src.backend.entrypoints.mqtt.mqtt_handler import MqttHandler, MqttSettings

    try:
        mqtt_settings = MqttSettings()
    except Exception:
        # Fallback на локальный брокер, если конфиг невалиден в dev-окружении.
        mqtt_settings = MqttSettings(
            broker_host="localhost", broker_port=1883, enabled=False
        )
    app.state.mqtt_handler = MqttHandler(mqtt_settings)


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


async def get_watermark_store(request: Request) -> WatermarkStore:
    """Возвращает :class:`WatermarkStore` из app.state (FastAPI Depends)."""
    return request.app.state.watermark_store
