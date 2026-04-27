"""Service DSL — декларативная регистрация сервисов с авто-созданием endpoints.

@service_dsl автоматически создаёт:
- ActionHandlerRegistry entries (→ REST/GraphQL/gRPC/SOAP/WS/SSE/MCP)
- Queue consumers (RabbitMQ/Kafka)
- Prefect tasks (через task_factory)
- DSL routes

@register_action — метод-декоратор для точечной регистрации без правки setup.py.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from pydantic import BaseModel

__all__ = (
    "service_dsl",
    "register_action",
    "scan_and_register_actions",
    "ServiceDSLRegistry",
    "ServiceMeta",
)

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
            meta.name,
            len(meta.methods),
            meta.protocols,
        )

    def list_services(self) -> list[ServiceMeta]:
        return list(self._services.values())

    def get(self, name: str) -> ServiceMeta | None:
        return self._services.get(name)

    def register_all_actions(self) -> None:
        """Регистрирует все actions из всех @service_dsl сервисов."""
        from src.dsl.commands.registry import action_handler_registry

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
            from src.workflows.task_factory import create_service_task
        except ImportError:
            return {}

        tasks: dict[str, Any] = {}
        from src.dsl.commands.registry import action_handler_registry

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
                m
                for m in dir(cls)
                if not m.startswith("_")
                and callable(getattr(cls, m, None))
                and m not in ("add", "get", "update", "delete")
            ]

        original_init = cls.__init__  # type: ignore[misc]

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

        cls._service_dsl_meta = meta  # type: ignore[attr-defined]
        return cls

    return decorator


# ─────────── Method-level @register_action ───────────

_ACTION_ATTR = "_action_meta"

_pending_actions: list[dict[str, Any]] = []


def register_action(
    action: str,
    *,
    payload_model: type[BaseModel] | None = None,
    service_getter: Callable[[], Any] | None = None,
):
    """Method-level decorator: marks a service method as an action handler.

    Usage::

        class OrderService(BaseService):
            @register_action("orders.create_skb_order", payload_model=OrderIdQuerySchema)
            async def create_skb_order(self, data): ...

    The getter is auto-detected from the module's ``get_<service>`` function,
    or can be provided explicitly.
    """

    def decorator(fn: Callable) -> Callable:
        meta = {
            "action": action,
            "method_name": fn.__name__,
            "payload_model": payload_model,
            "service_getter": service_getter,
            "fn": fn,
        }
        setattr(fn, _ACTION_ATTR, meta)
        _pending_actions.append(meta)
        return fn

    return decorator


def _find_getter_in_module(
    module: Any, method_owner_cls: type | None
) -> Callable | None:
    """Auto-detect ``get_<name>_service`` or ``get_<name>`` factory in the module."""
    for name in dir(module):
        obj = getattr(module, name, None)
        if callable(obj) and name.startswith("get_") and not isinstance(obj, type):
            return obj
    return None


def scan_and_register_actions(package_paths: Sequence[str] | None = None) -> int:
    """Import all modules in given packages and register @register_action-decorated methods.

    Returns the number of actions registered.
    """
    from src.dsl.commands.registry import action_handler_registry

    if package_paths:
        for pkg_path in package_paths:
            try:
                pkg = importlib.import_module(pkg_path)
                if hasattr(pkg, "__path__"):
                    for importer, modname, ispkg in pkgutil.walk_packages(
                        pkg.__path__, prefix=pkg.__name__ + "."
                    ):
                        try:
                            importlib.import_module(modname)
                        except ImportError:
                            pass
            except ImportError:
                logger.warning("Cannot import package %s for action scan", pkg_path)

    count = 0
    for meta in _pending_actions:
        if action_handler_registry.is_registered(meta["action"]):
            continue

        getter = meta["service_getter"]
        if getter is None:
            fn = meta["fn"]
            module = inspect.getmodule(fn)
            if module is not None:
                getter = _find_getter_in_module(module, None)

        if getter is None:
            logger.warning(
                "No service_getter found for action '%s', skipping", meta["action"]
            )
            continue

        action_handler_registry.register(
            action=meta["action"],
            service_getter=getter,
            service_method=meta["method_name"],
            payload_model=meta["payload_model"],
        )
        count += 1

    logger.info("Auto-registered %d actions from @register_action decorators", count)
    return count
