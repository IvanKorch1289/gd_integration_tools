"""Backward-compat shim — ``health`` стал package.

W9 P2-13 Phase 4 (cycle 153, MINIMAX plan): ``health.py`` (609 LOC god-module)
→ ``health/`` package с 4 cohesion submodules (см. ADR-0329). Этот модуль —
thin re-export shim для backward-compat: ``from services.ops.health import X``
продолжает работать для всех публичных имён.

Migration::

    # До (W9 P2-13 Phase 4 — still works через этот shim):
    from src.backend.services.ops.health import (
        ProcessorHealthService, ProcessorHealthResult, get_processor_health_service,
    )

    # После (canonical, рекомендуется для нового кода):
    from src.backend.services.ops.health import (
        ProcessorHealthService, ProcessorHealthResult, get_processor_health_service,
    )
    # Тот же путь — split прозрачен для consumers.

Removal: запланирован на cycle 162 (отдельный cleanup wave после telemetry
audit consumer migration).
"""

from __future__ import annotations

from src.backend.services.ops.health import (  # type: ignore[attr-defined]
    ProcessorHealthResult as ProcessorHealthResult,
)
from src.backend.services.ops.health import (
    ProcessorHealthService as ProcessorHealthService,
)
from src.backend.services.ops.health import (
    get_processor_health_service as get_processor_health_service,
)

__all__ = (
    "ProcessorHealthResult",
    "ProcessorHealthService",
    "get_processor_health_service",
)
