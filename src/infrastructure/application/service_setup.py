"""
Регистрация всех бизнес-сервисов в едином DI-контейнере ``svcs_registry``.

Располагается в infrastructure/application/ (не в core/) согласно Clean
Architecture: composition root должен знать о всех слоях проекта и
находиться во внешнем слое.

Вызывается один раз при старте приложения из lifespan.
"""

from __future__ import annotations

from src.core.svcs_registry import register_factory

__all__ = ("register_all_services",)


def register_all_services() -> None:
    """
    Регистрирует все бизнес-сервисы приложения в svcs_registry.

    Импорты фабрик сервисов делаются lazy (внутри функции), чтобы
    избежать cycle-импортов и держать холодный старт быстрым.
    """
    from src.services.ai.ai_agent import get_ai_agent_service
    from src.services.core.admin import get_admin_service
    from src.services.core.orderkinds import get_order_kind_service
    from src.services.core.orders import get_order_service
    from src.services.core.tech import get_tech_service
    from src.services.core.users import get_user_service
    from src.services.integrations.dadata import get_dadata_service
    from src.services.integrations.skb import get_skb_service
    from src.services.io.files import get_file_service

    register_factory("orders", get_order_service)
    register_factory("users", get_user_service)
    register_factory("files", get_file_service)
    register_factory("orderkinds", get_order_kind_service)
    register_factory("skb", get_skb_service)
    register_factory("dadata", get_dadata_service)
    register_factory("tech", get_tech_service)
    register_factory("admin", get_admin_service)
    register_factory("ai", get_ai_agent_service)

    from src.services.ai.agent_memory import get_agent_memory_service
    from src.services.ai.rag_service import get_rag_service
    from src.services.io.search import get_search_service
    from src.services.ops.analytics import get_analytics_service
    from src.services.ops.webhook_scheduler import get_webhook_scheduler

    register_factory("analytics", get_analytics_service)
    register_factory("search", get_search_service)
    register_factory("rag", get_rag_service)
    register_factory("agent_memory", get_agent_memory_service)
    register_factory("webhook", get_webhook_scheduler)
