"""DSL service-level: декларативная регистрация сервисов через service.toml.

Sprint 9 K3 W6: консолидация бывшего ``dsl/service.py`` (DslService
facade) с пакетом ``dsl/service/`` (ServiceDSLRegistry). Раньше Python
делал shadowing — теперь обе вещи в одном пакете.
"""

from src.backend.dsl.service.facade import DslService, get_dsl_service
from src.backend.dsl.service.registry import ServiceDSLRegistry, get_service_registry
from src.backend.dsl.service.toml_loader import (
    ServiceSpec,
    load_service_toml,
    scan_services,
)

__all__ = (
    "DslService",
    "ServiceDSLRegistry",
    "ServiceSpec",
    "get_dsl_service",
    "get_service_registry",
    "load_service_toml",
    "scan_services",
)
