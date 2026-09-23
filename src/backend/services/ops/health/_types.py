"""Shared types для processor health checks (Sprint 6 K2 — W9 P2-13 Phase 4).

W9 P2-13 Phase 4 (cycle 153): извлечено из ``services/ops/health.py`` (609 LOC
god-module). Содержит ``ProcessorHealthResult`` dataclass.

Back-compat: ``services/ops/health.py`` (file) продолжает re-export через
thin ``__init__.py`` shim (см. ADR-0329).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProcessorHealthResult:
    """Результат одной processor-check проверки.

    Attributes:
        ok: True если backend доступен и отвечает в ожидаемое время.
        reason: Краткое описание (для UI / Grafana / alert).
        latency_ms: Время выполнения проверки (мс).
        processor_name: Логическое имя backend-сервиса.

    """

    processor_name: str
    ok: bool
    reason: str
    latency_ms: float
