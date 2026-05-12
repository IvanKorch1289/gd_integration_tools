"""Реестр процессоров и связанных артефактов DSL (Stage 3, V15 Sprint 1).

Public API:
    * :func:`processor` — декоратор регистрации.
    * :class:`ProcessorRegistry` — реестр.
    * :class:`ProcessorSpec` — спецификация записи.
    * :func:`get_processor_registry` — global singleton.
    * Исключения: :class:`ProcessorConflictError`,
      :class:`ProcessorNotFoundError`, :class:`CapabilityDeniedError`.
"""

from __future__ import annotations

from src.backend.dsl.registry.errors import (
    CapabilityDeniedError,
    ProcessorConflictError,
    ProcessorNotFoundError,
    ProcessorRegistryError,
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
    "get_processor_registry",
    "processor",
)
