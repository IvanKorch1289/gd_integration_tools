"""Shared types для privacy/data-subject erasure (Sprint 1 — audit 2026-09-22 P1).

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module). Содержит ErasureStrategy + ErasureResultStatus enums,
AdapterResult + OrchestratorResult dataclasses, ErasureAdapter Protocol.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export этих
символов через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class ErasureStrategy(str, Enum):
    """Стратегия erasure."""

    HARD_DELETE = "hard_delete"  # удалить навсегда
    ANONYMIZE = "anonymize"  # заменить PII на плейсхолдеры


class ErasureResultStatus(str, Enum):
    """Status отдельной adapter operation."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # legal hold или dry-run


@dataclass(slots=True)
class AdapterResult:
    """Result одной adapter operation."""

    adapter_name: str
    status: ErasureResultStatus
    duration_ms: float
    records_affected: int = 0
    error: str | None = None


@dataclass(slots=True)
class OrchestratorResult:
    """Result полного DeleteDataSubject execution."""

    subject_id: str
    subject_type: str
    reason: str
    correlation_id: str
    started_at: float
    completed_at: float
    strategy: ErasureStrategy
    adapter_results: list[AdapterResult] = field(default_factory=list)
    legal_hold_active: bool = False
    tombstone_published: bool = False

    @property
    def success(self) -> bool:
        """True если все critical adapters succeeded."""
        return all(r.status != ErasureResultStatus.FAILED for r in self.adapter_results)

    @property
    def total_records(self) -> int:
        """Сумма records_affected по всем adapter-results."""
        return sum(r.records_affected for r in self.adapter_results)


class ErasureAdapter(Protocol):
    """Protocol для всех erasure adapters.

    Per ADR-0345 Option A: tenant-aware per-call enforcement.
    ``tenant_id`` keyword-only — explicit override caller-facing.
    Adapters обязаны apply tenant filter when ``tenant_id`` provided.
    """

    name: str

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> AdapterResult:
        """Выполнить erasure субъекта в домене адаптера.

        Args:
            subject_id: stable internal identity (e.g., "user:42").
            subject_type: тип субъекта ("user", "tenant", etc.).
            strategy: hard_delete или anonymize.
            correlation_id: request correlation id.
            tenant_id: tenant scope filter. None → adapter resolves via
                ``current_tenant()`` from TenantContext (per ADR-0345).
                Per-call override: caller can pass explicit value.

        Returns:
            AdapterResult с per-adapter results.
        """
        ...
