"""Service DSL — декларативная регистрация сервисов с авто-созданием endpoints.

@service_dsl автоматически создаёт:
- ActionHandlerRegistry entries (→ REST/GraphQL/gRPC/SOAP/WS/SSE/MCP)
- Queue consumers (RabbitMQ/Kafka)
- Prefect tasks (через task_factory)
- DSL routes
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from pydantic import BaseModel

__all__ = ("service_dsl", "ServiceDSLRegistry", "ServiceMeta")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ServiceMeta:
    name: str
    service_cls: type
    service_getter: Callable
    schema_in: type[BaseModel] | None = None
    schema_out: type[BaseModel] | None = None
    protocols: Sequence[str] = ("all",)
    methods: list[str] = field(default_factory=list)
    crud: bool = True


class ServiceDSLRegistry:
    """Реестр сервисов, зарегистрированных через @service_dsl."""

    def __init__(self) -> None:
        self._services: dict[str, ServiceMeta] = {}

    def register(self, meta: ServiceMeta) -> None:
        self._services[meta.name] = meta
        logger.info(
            "ServiceDSL registered: %s (%d methods, protocols=%s)",
            meta.name, len(meta.methods), meta.protocols,
        )

    def list_services(self) -> list[ServiceMeta]:
        return list(self._services.values())

    def get(self, name: str) -> ServiceMeta | None:
        return self._services.get(name)

    def register_all_actions(self) -> None:
        """Регистрирует все actions из всех @service_dsl сервисов."""
        from app.dsl.commands.registry import ActionHandlerSpec, action_handler_registry

        for meta in self._services.values():
            if meta.crud:
                for method in ("add", "get", "update", "delete"):
                    if hasattr(meta.service_cls, method):
                        action_handler_registry.register(
                            action=f"{meta.name}.{method}",
                            service_getter=meta.service_getter,
                            service_method=method,
                        )

            for method_name in meta.methods:
                if hasattr(meta.service_cls, method_name):
                    action_handler_registry.register(
                        action=f"{meta.name}.{method_name}",
                        service_getter=meta.service_getter,
                        service_method=method_name,
                    )

    def generate_prefect_tasks(self) -> dict[str, Any]:
        """Генерирует Prefect tasks для всех зарегистрированных actions."""
        try:
            from app.workflows.task_factory import create_service_task
        except ImportError:
            return {}

        tasks: dict[str, Any] = {}
        from app.dsl.commands.registry import action_handler_registry

        for meta in self._services.values():
            if "prefect" not in meta.protocols and "all" not in meta.protocols:
                continue
            prefix = f"{meta.name}."
            for action in action_handler_registry.list_actions():
                if action.startswith(prefix):
                    tasks[action] = create_service_task(action)
        return tasks


service_dsl_registry = ServiceDSLRegistry()


def service_dsl(
    name: str,
    *,
    schema_in: type[BaseModel] | None = None,
    schema_out: type[BaseModel] | None = None,
    protocols: Sequence[str] = ("all",),
    crud: bool = True,
    methods: Sequence[str] | None = None,
):
    """Декоратор для декларативной регистрации сервиса.

    Пример:
        @service_dsl(name="invoices", schema_in=InvoiceIn, protocols=["rest", "grpc", "prefect"])
        class InvoiceService(BaseService):
            async def create(self, data): ...
            async def approve(self, invoice_id): ...
    """

    def decorator(cls: type) -> type:
        discovered_methods = methods
        if discovered_methods is None:
            discovered_methods = [
                m for m in dir(cls)
                if not m.startswith("_")
                and callable(getattr(cls, m, None))
                and m not in ("add", "get", "update", "delete")
            ]

        original_init = cls.__init__

        _instance = [None]

        def getter():
            if _instance[0] is None:
                _instance[0] = cls.__new__(cls)
                try:
                    original_init(_instance[0])
                except TypeError:
                    pass
            return _instance[0]

        meta = ServiceMeta(
            name=name,
            service_cls=cls,
            service_getter=getter,
            schema_in=schema_in,
            schema_out=schema_out,
            protocols=list(protocols),
            methods=list(discovered_methods),
            crud=crud,
        )
        service_dsl_registry.register(meta)

        cls._service_dsl_meta = meta
        return cls

    return decorator
