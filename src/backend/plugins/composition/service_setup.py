"""
Регистрация всех бизнес-сервисов в едином DI-контейнере ``svcs_registry``.

Располагается в infrastructure/application/ (не в core/) согласно Clean
Architecture: composition root должен знать о всех слоях проекта и
находиться во внешнем слое.

Вызывается один раз при старте приложения из lifespan.
"""

from __future__ import annotations

import os

from src.backend.core.logging import get_logger
from src.backend.core.svcs_registry import has_service, register_factory

__all__ = (
    "register_all_services",
    "register_default_action_middlewares",
    "register_secrets_backend",
)

_logger = get_logger("composition.service_setup")


def register_default_action_middlewares() -> None:
    """Регистрирует встроенные middleware action-диспетчера (W14.1.C).

    Порядок: ``audit`` → ``idempotency`` → ``rate_limit``.
    Идемпотентность по факту повторного вызова: проверяем, что
    middleware с тем же типом ещё не зарегистрирован, чтобы избежать
    двойной регистрации при перезапуске lifespan в тестах.
    """
    from src.backend.dsl.commands.action_registry import action_handler_registry
    from src.backend.services.execution.middlewares import (
        AuditMiddleware,
        IdempotencyMiddleware,
        RateLimitMiddleware,
    )

    existing_types = {type(mw) for mw in action_handler_registry.list_middleware()}
    for cls in (AuditMiddleware, IdempotencyMiddleware, RateLimitMiddleware):
        if cls not in existing_types:
            action_handler_registry.register_middleware(cls())


def register_secrets_backend() -> None:
    """Регистрирует ``SecretsBackend`` в svcs по флагу ``SECRETS_BACKEND``.

    * ``env`` (по умолчанию) — :class:`EnvSecretsBackend` (os.environ).
    * ``vault`` — заглушка: реальная реализация выполняется в Wave K вместе
      с ``docker-compose.prod.yml``. До этого момента lookup по ключу
      ``vault`` падает осмысленным ``NotImplementedError``.

    Идемпотентно: повторный вызов не пересоздаёт фабрику.
    """
    from src.backend.core.interfaces.secrets import SecretsBackend

    if has_service(SecretsBackend):
        return

    backend_kind = os.environ.get("SECRETS_BACKEND", "env").strip().lower()

    def _factory() -> SecretsBackend:
        match backend_kind:
            case "env":
                from src.backend.infrastructure.security.env_secrets import (
                    EnvSecretsBackend,
                )

                return EnvSecretsBackend()
            case "vault":
                raise NotImplementedError(
                    "VaultSecretsBackend будет реализован в Wave K. "
                    "До этого момента используйте SECRETS_BACKEND=env."
                )
            case _:
                raise ValueError(
                    f"Неизвестный SECRETS_BACKEND={backend_kind!r}; "
                    "поддерживаются: env, vault."
                )

    register_factory(SecretsBackend, _factory)
    _logger.info("SecretsBackend registered: kind=%s", backend_kind)


def _register_storage_facade() -> None:
    """Регистрирует ``StorageFacade`` в svcs с capability-check."""
    from src.backend.core.svcs_registry import has_service, register_factory
    from src.backend.services.storage import StorageFacade

    if has_service(StorageFacade):
        return

    def _factory() -> StorageFacade:
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.core.svcs_registry import get_service, has_service
        from src.backend.infrastructure.storage.factory import get_object_storage

        storage = get_object_storage()
        capability_check = None
        if has_service(CapabilityGate):
            gate = get_service(CapabilityGate)
            capability_check = getattr(gate, "check", None)
        return StorageFacade(
            storage=storage, capability_check=capability_check, plugin="system"
        )

    register_factory(StorageFacade, _factory)


def _register_cache_facade() -> None:
    """Регистрирует ``UnifiedCacheFacade`` в svcs с tiered fallback."""
    from src.backend.core.svcs_registry import has_service, register_factory
    from src.backend.services.cache import UnifiedCacheFacade

    if has_service(UnifiedCacheFacade):
        return

    def _factory() -> UnifiedCacheFacade:
        from pathlib import Path

        from src.backend.core.config.services.cache import cache_settings
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.core.svcs_registry import get_service, has_service
        from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend
        from src.backend.infrastructure.cache.factory import create_cache_backend

        primary = create_cache_backend(cache_settings)
        memory = MemoryBackend(maxsize=cache_settings.l1_maxsize)
        disk_path = getattr(cache_settings, "disk_fallback_path", None) or Path(
            "var/cache/disk_fallback"
        )
        disk = DiskCacheBackend(disk_path)

        capability_check = None
        if has_service(CapabilityGate):
            gate = get_service(CapabilityGate)
            capability_check = getattr(gate, "check", None)

        return UnifiedCacheFacade(
            primary=primary,
            memory_fallback=memory,
            disk_fallback=disk,
            capability_check=capability_check,
            plugin="system",
        )

    register_factory(UnifiedCacheFacade, _factory)


def _register_external_database_facade() -> None:
    """Регистрирует ``ExternalDatabaseFacade`` в svcs с capability-check."""
    from src.backend.core.svcs_registry import has_service, register_factory
    from src.backend.infrastructure.database.external_database_facade import (
        ExternalDatabaseFacade,
    )

    if has_service(ExternalDatabaseFacade):
        return

    def _factory() -> ExternalDatabaseFacade:
        from src.backend.core.di.providers import get_external_session_manager_provider
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.core.svcs_registry import get_service, has_service

        session_manager_factory = get_external_session_manager_provider()

        capability_check = None
        if has_service(CapabilityGate):
            gate = get_service(CapabilityGate)
            capability_check = getattr(gate, "check", None)

        return ExternalDatabaseFacade(
            session_manager_factory=session_manager_factory,
            capability_check=capability_check,
            plugin="system",
        )

    register_factory(ExternalDatabaseFacade, _factory)


def register_all_services() -> None:
    """
    Регистрирует все бизнес-сервисы приложения в svcs_registry.

    Импорты фабрик сервисов делаются lazy (внутри функции), чтобы
    избежать cycle-импортов и держать холодный старт быстрым.
    """
    from extensions.core_entities.orderkinds.services.orderkinds import (
        get_order_kind_service,
    )
    from extensions.core_entities.orders.services.orders import get_order_service
    from extensions.core_entities.users.services.users import get_user_service
    from src.backend.services.ai.ai_agent import get_ai_agent_service
    from src.backend.services.core.admin import get_admin_service
    from src.backend.services.core.tech import get_tech_service
    from src.backend.services.integrations.dadata import get_dadata_service
    from src.backend.services.integrations.skb import get_skb_service
    from src.backend.services.io.files import get_file_service

    register_factory("orders", get_order_service)
    register_factory("users", get_user_service)
    register_factory("files", get_file_service)
    register_factory("orderkinds", get_order_kind_service)
    register_factory("skb", get_skb_service)
    register_factory("dadata", get_dadata_service)
    register_factory("tech", get_tech_service)
    register_factory("admin", get_admin_service)
    register_factory("ai", get_ai_agent_service)

    from src.backend.services.ai.agent_memory import get_agent_memory_service
    from src.backend.services.ai.rag_service import get_rag_service
    from src.backend.services.io.search import get_search_service
    from src.backend.services.ops.analytics import get_analytics_service
    from src.backend.services.ops.webhook_scheduler import get_webhook_scheduler

    register_factory("analytics", get_analytics_service)
    register_factory("search", get_search_service)
    register_factory("rag", get_rag_service)
    register_factory("agent_memory", get_agent_memory_service)
    register_factory("webhook", get_webhook_scheduler)

    # GAP-B: LangMemService singleton через DI вместо module-level _singleton.
    from src.backend.services.ai.memory.langmem_service import get_langmem_service

    register_factory("langmem", get_langmem_service)

    # Wave A: SecretsBackend через svcs (env/vault dispatch).
    register_secrets_backend()

    # P1: StorageFacade для extensions (S133 W4).
    _register_storage_facade()

    # P1: UnifiedCacheFacade (S133 W4).
    _register_cache_facade()

    # P1: ExternalDatabaseFacade (S133 W4).
    _register_external_database_facade()

    # W14.1.C: встроенные middleware action-диспетчера.
    register_default_action_middlewares()
