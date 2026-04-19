"""Регистрация всех бизнес-сервисов в ServiceRegistry.

Вызывается один раз при старте приложения.
"""

from app.core.service_registry import service_registry

__all__ = ("register_all_services",)


def register_all_services() -> None:
    """Регистрирует все бизнес-сервисы приложения."""
    from app.services.admin import get_admin_service
    from app.services.ai_agent import get_ai_agent_service
    from app.services.dadata import get_dadata_service
    from app.services.files import get_file_service
    from app.services.orderkinds import get_order_kind_service
    from app.services.orders import get_order_service
    from app.services.skb import get_skb_service
    from app.services.tech import get_tech_service
    from app.services.users import get_user_service

    service_registry.register("orders", get_order_service)
    service_registry.register("users", get_user_service)
    service_registry.register("files", get_file_service)
    service_registry.register("orderkinds", get_order_kind_service)
    service_registry.register("skb", get_skb_service)
    service_registry.register("dadata", get_dadata_service)
    service_registry.register("tech", get_tech_service)
    service_registry.register("admin", get_admin_service)
    service_registry.register("ai", get_ai_agent_service)

    from app.services.analytics import get_analytics_service
    from app.services.search import get_search_service
    from app.services.rag_service import get_rag_service
    from app.services.agent_memory import get_agent_memory_service
    from app.services.webhook_scheduler import get_webhook_scheduler

    service_registry.register("analytics", get_analytics_service)
    service_registry.register("search", get_search_service)
    service_registry.register("rag", get_rag_service)
    service_registry.register("agent_memory", get_agent_memory_service)
    service_registry.register("webhook", get_webhook_scheduler)
