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
    from src.backend.core.security.authorization_gateway import (
        AuthorizationGateway,  # Cycle-19 (D-AUDIT-1907): forward-ref для get_authorization_gateway
    )
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
    "_get_from_app_state",
    "app_state_singleton",
    "get_api_key_manager",
    # Round 88: AuthorizationGateway Depends (Sprint 1 K5).
    "get_authorization_gateway",
    "get_langfuse_client",
    "get_mqtt_handler",
    "get_pipeline_version_manager",
    "get_plugin_registry",
    "get_pool_monitor",
    "get_slo_tracker",
    "get_tracer",
    "get_vault_refresher",
    "get_watermark_store",
    "register_app_state",
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
    # Sprint 1.3: AIGateway singleton с обязательными DI (S177 M2 guard).
    from src.backend.core.di.providers.ai import get_ai_gateway_provider

    app.state.ai_gateway = get_ai_gateway_provider()

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

    # Round 88: AuthorizationGateway singleton registration (Sprint 1 K5).
    # До этого: app.state.authorization_gateway отсутствовал → PolicyMixin
    # _resolve_authz_gateway всегда возвращал None → LLM policy-gate работал
    # только в fail-closed режиме. Регистрация как lazy singleton:
    # создаётся один раз при старте, переиспользуется в каждом request.
    # B-12 fix (cycle 37): production wiring OPA/Casbin в composition root.
    from src.backend.core.security.authorization_gateway import AuthorizationGateway
    from src.backend.services.admin._capability_adapter import FacadeCapabilityAdapter
    from src.backend.services.capabilities.facade import get_capability_facade

    # B-12 fix (cycle 37): инстанциация OPA/Casbin только при явной активации
    # через ``policy_settings.engine_enabled`` (default OFF на dev/dev_light).
    # На prod-профиле YAML-overlay поднимает флаг → реальные движки подцепляются.
    # B-20 fix (cycle 38): auth_policies fail-loud при engine_enabled=True
    # без сконфигурированных OPA/Casbin (fake-active security). До этого
    # silent skip log-warning при пустых URL приводил к регистрации
    # AuthorizationGateway с пустой policies chain → LLM policy-gate работал
    # только в fail-closed capability-check. На prod-профиле это становится
    # P0: разрешает prod запуск с engine_enabled=True, но без фактически
    # работающих policy-движков. Каждый движок по-прежнему опционален
    # (OPA-only / Casbin-only — валидные конфигурации), но ОБА пустыми
    # быть не могут.
    auth_policies: list = []
    try:
        from src.backend.core.config.services.policy import policy_settings

        if policy_settings.engine_enabled:
            if not policy_settings.opa_url and not policy_settings.casbin_model_path:
                # B-20 fix (cycle 38): fail-loud — production-wiring с
                # engine_enabled=True обязан иметь хотя бы один policy-engine.
                from src.backend.core.errors import ProductionWiringError

                raise ProductionWiringError(
                    message=(
                        "policy.engine_enabled=True requires at least one of "
                        "policy.opa_url or policy.casbin_model_path to be set"
                    ),
                    missing=(
                        "policy.opa_url",
                        "policy.casbin_model_path",
                    ),
                )
            from src.backend.core.security.authorization_gateway.policies import (
                build_casbin_policy_decider,
                build_opa_policy_decider,
            )
            from src.backend.infrastructure.policy.casbin_adapter import CasbinAdapter
            from src.backend.infrastructure.policy.casbin_tenant_scoped import (
                TenantScopedCasbin,
            )
            from src.backend.infrastructure.policy.opa.client import OPAClient

            # OPA + Casbin поднимаются как обычные singletons; ``policies``
            # получает упорядоченную цепочку: сначала OPA (data-level), потом
            # Casbin (RBAC/ABAC). Любой из них опционален — если путь None,
            # соответствующий policy-engine просто не регистрируется.
            if policy_settings.opa_url:
                opa_client = OPAClient(base_url=policy_settings.opa_url)
                auth_policies.append(
                    build_opa_policy_decider(
                        opa_client, policy_name=policy_settings.opa_policy_name,
                    ),
                )
            if policy_settings.casbin_model_path:
                casbin_base = CasbinAdapter(
                    model_path=policy_settings.casbin_model_path,
                    policy_path=policy_settings.casbin_policy_path,
                )
                auth_policies.append(
                    build_casbin_policy_decider(
                        TenantScopedCasbin(base_adapter=casbin_base),
                    ),
                )
            from src.backend.core.logging import get_logger as _gl

            _gl("policy.composition").info(
                "policy engines wired (opa=%s, casbin=%s)",
                bool(policy_settings.opa_url),
                bool(policy_settings.casbin_model_path),
            )
    except ProductionWiringError:
        # B-20 fix (cycle 38): production-wiring ошибки пробрасываются
        # наружу — fail-loud запрещает fake-active security.
        raise
    except Exception as _pol_exc:
        # Fail-soft при ошибке сборки (например, OPA-клиент пытается
        # выполнить make_http_client во время DI). В prod это должно
        # попасть в лог-агрегатор; цепочка остаётся пустой (capability check
        # остаётся единственной обязательной policy — fail-closed).
        from src.backend.core.logging import get_logger as _gl

        _gl("policy.composition").warning(
            "policy engines NOT wired (engine_enabled but init failed): %s",
            _pol_exc,
        )

    app.state.authorization_gateway = AuthorizationGateway(
        capability_gateway=FacadeCapabilityAdapter(get_capability_facade()),
        policies=tuple(auth_policies),
    )

    # W14.5: durable WatermarkStore — выбор бэкенда (memory/postgres) по
    # ``WatermarkSettings``. PG-вариант берёт главный session_manager;
    # memory не требует БД и пригоден для dev_light/тестов.
    from src.backend.core.config.services.watermark import (
        watermark_settings as _watermark_settings,
    )
    from src.backend.infrastructure.database.session_manager import main_session_manager
    from src.backend.infrastructure.watermark.factory import create_watermark_store

    app.state.watermark_store = create_watermark_store(
        _watermark_settings, session_manager=main_session_manager,
    )

    from src.backend.entrypoints.mqtt.mqtt_handler import MqttHandler, MqttSettings

    try:
        mqtt_settings = MqttSettings()
    except Exception as _:
        # Fallback: use class defaults (MqttSettings already has broker_host="localhost", broker_port=1883)
        mqtt_settings = MqttSettings(enabled=False)
    app.state.mqtt_handler = MqttHandler(mqtt_settings)

    # B-17 fix (cycle 37): production fail-loud DLQ wiring для CDCClient.
    # До этого setter ``set_dlq_writer`` существовал (S176 cycle 33 B-02),
    # но никем не вызывался → silent event loss при сбое callback/dispatch.
    # Подключаем InboxDLQWriter к singleton CDCClient через тот же
    # session_factory, что и outbox DLQ handler.
    from src.backend.infrastructure.clients.external.cdc import get_cdc_client
    from src.backend.infrastructure.messaging.dlq.inbox_writer import InboxDLQWriter
    from src.backend.plugins.composition.lifecycle.outbox_setup import (
        _get_outbox_dlq_session_factory,
    )

    cdc_singleton = get_cdc_client()
    inbox_dlq_writer = InboxDLQWriter(
        session_factory=_get_outbox_dlq_session_factory(),
    )
    cdc_singleton.set_dlq_writer(inbox_dlq_writer)
    # mark_cdc_dlq_writer_wired вызывается автоматически из
    # ``set_dlq_writer`` для не-None writer, но делаем явный mark
    # для observability (счётчик в guard обновляется дважды, idempotent).
    from src.backend.infrastructure.clients.external.cdc._dlq_writer_guard import (
        mark_cdc_dlq_writer_wired,
    )

    mark_cdc_dlq_writer_wired(inbox_dlq_writer)


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


# Round 88: FastAPI Depends wrapper для AuthorizationGateway (Sprint 1 K5).
# Test requires asyncio.iscoroutinefunction(di.get_authorization_gateway) → True.
async def get_authorization_gateway(
    request: Request,
) -> AuthorizationGateway:
    """Возвращает AuthorizationGateway из app.state (FastAPI Depends)."""
    return request.app.state.authorization_gateway


async def get_langfuse_client(request: Request) -> LangFuseClient:
    """Возвращает LangFuseClient из app.state (FastAPI Depends)."""
    return request.app.state.langfuse_client


async def get_watermark_store(request: Request) -> WatermarkStore:
    """Возвращает :class:`WatermarkStore` из app.state (FastAPI Depends)."""
    return request.app.state.watermark_store
