"""Реестр процессоров и связанных артефактов DSL (Stage 3, V15 Sprint 1).

Public API:
    * :func:`processor` — декоратор регистрации.
    * :class:`ProcessorRegistry` — реестр процессоров.
    * :class:`ProcessorSpec` — спецификация записи.
    * :func:`get_processor_registry` — global singleton.
    * :class:`RouteRegistry`, :data:`route_registry` — реестр DSL-маршрутов
      (canonical модуль — :mod:`src.backend.dsl.commands.registry`).
    * Исключения: :class:`ProcessorConflictError`,
      :class:`ProcessorNotFoundError`, :class:`CapabilityDeniedError`.
"""

from __future__ import annotations

from src.backend.dsl.commands.registry import RouteRegistry as RouteRegistry
from src.backend.dsl.commands.registry import route_registry as route_registry
from src.backend.dsl.registry.errors import (
    CapabilityDeniedError,
    ProcessorConflictError,
    ProcessorNotFoundError,
    ProcessorRegistryError,
)
from src.backend.dsl.registry.json_schema_exporter import (
    export_processors_schema as export_processors_schema,
)
from src.backend.dsl.registry.processor import (
    ProcessorRegistry,
    ProcessorSpec,
    get_processor_registry,
    processor,
)

__all__ = (
    "CapabilityDeniedError",
    "ProcessorConflictError",
    "ProcessorNotFoundError",
    "ProcessorRegistry",
    "ProcessorRegistryError",
    "ProcessorSpec",
    "RouteRegistry",
    "export_processors_schema",
    "get_processor_registry",
    "processor",
    "route_registry",
)
