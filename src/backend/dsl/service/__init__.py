"""DSL service-level: декларативная регистрация сервисов через service.toml."""

from src.backend.dsl.service.registry import ServiceDSLRegistry, get_service_registry
from src.backend.dsl.service.toml_loader import (
    ServiceSpec,
    load_service_toml,
    scan_services,
)

__all__ = (
    "ServiceDSLRegistry",
    "ServiceSpec",
    "get_service_registry",
    "load_service_toml",
    "scan_services",
)
