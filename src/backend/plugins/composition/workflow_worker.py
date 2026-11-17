"""Composition wiring для standalone workflow worker.

Worker находится в infrastructure и не должен знать о DSL. Этот модуль —
единственная точка, где standalone worker получает DSL-регистрации; сам
worker вызывает функцию через инъекцию callback'а.
"""

from __future__ import annotations

__all__ = ("register_worker_dependencies",)


def register_worker_dependencies() -> None:
    """Зарегистрировать сервисы, action-handler'ы и DSL-маршруты worker'а.

    Порядок регистрации совпадает с прежним production-поведением:
    сервисы → action-handler'ы → DSL-маршруты.
    """
    from src.backend.dsl.commands.setup.orchestrator import register_action_handlers
    from src.backend.dsl.routes import register_dsl_routes
    from src.backend.plugins.composition.service_setup import register_all_services

    register_all_services()
    register_action_handlers()
    register_dsl_routes()
