"""Processor health-check subpackage (W9 P2-13 Phase 4).

W9 P2-13 Phase 4 (cycle 153, MINIMAX plan): извлечено из
``services/ops/health.py`` (609 LOC god-module) в package с 4 cohesion
submodules (см. ADR-0329).

Back-compat: ``services/ops/health.py`` (singular, файл) → thin re-export shim.
``services/ops/__init__.py`` (public API facade) без изменений.

Public API:
    from src.backend.services.ops.health import (  # noqa: F401 — re-export
        ProcessorHealthService, ProcessorHealthResult,
        get_processor_health_service,
    )

Submodules:
    _types.py — ProcessorHealthResult dataclass
    _http.py — _http_get, _tcp_connect utilities (low-level probes)
    _service.py — ProcessorHealthService + get_processor_health_service singleton
    _checks.py — 7 default processor checks (Kafka SR, Temporal, Vault, ClickHouse,
                Redis cluster, NATS, Graylog) + _is_strict_mode helper

Endpoint: ``GET /health/processors`` — агрегированная матрица processor-checks.
"""

from __future__ import annotations

from src.backend.services.ops.health._service import (  # noqa: F401 — re-export
    ProcessorHealthService as ProcessorHealthService,
)
from src.backend.services.ops.health._service import (  # noqa: F401 — re-export
    get_processor_health_service as get_processor_health_service,
)
from src.backend.services.ops.health._types import (  # noqa: F401 — re-export
    ProcessorHealthResult as ProcessorHealthResult,
)

__all__ = (
    "ProcessorHealthResult",
    "ProcessorHealthService",
    "get_processor_health_service",
)
