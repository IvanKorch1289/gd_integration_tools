from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

"""Data Quality Monitor — авто-детект схемы + аномалии.

Проверки:
- Missing required fields (NULL/empty)
- Type violations (string in numeric field)
- Outliers (Z-score > 3σ)
- Duplicate records (same PK within window)
- Late-arriving data (> threshold old)
- Schema drift (новые/удалённые поля)

Actions: dq.check, dq.schema_infer, dq.stats, dq.rules
"""

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class DQSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(slots=True)
class DQViolation:
    rule: str
    field: str
    severity: DQSeverity
    message: str
    value: Any = None


@dataclass(slots=True)
class DQCheckResult:
    violations: list[DQViolation] = dataclass_field(default_factory=list)
    passed: int = 0
    failed: int = 0

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0


# DQRemediationResult lives in __init__.py (S153 W1: 5x dedup)
@dataclass(slots=True)
class DQRule:
    """Правило проверки качества данных."""

    name: str
    field: str
    check: str  # "not_null", "type", "range", "unique", "regex"
    params: dict[str, Any] = dataclass_field(default_factory=dict)
    severity: DQSeverity = DQSeverity.WARNING
    enabled: bool = True


class SchemaMixin:
    """schema inference + statistics для DataQualityMonitor. S55 W4 extraction."""

    __slots__ = ()

    async def schema_infer(
        self, data: dict[str, Any] | list[dict[str, Any]], dataset: str = "default"
    ) -> dict[str, Any]:
        """Инферит схему из данных."""
        records = data if isinstance(data, list) else [data]
        schema: dict[str, set[str]] = defaultdict(set)

        for record in records:
            for k, v in record.items():
                schema[k].add(type(v).__name__)

        inferred = {k: list(v) for k, v in schema.items()}
        prev = self._inferred_schemas.get(dataset)
        drift: dict[str, str] = {}
        if prev:
            for k in set(inferred) - set(prev):
                drift[k] = "new_field"
            for k in set(prev) - set(inferred):
                drift[k] = "missing_field"

        self._inferred_schemas[dataset] = {
            k: list(v)[0] if len(v) == 1 else str(v) for k, v in schema.items()
        }
        return {
            "schema": self._inferred_schemas[dataset],
            "drift": drift,
            "fields": len(inferred),
        }

    async def stats(self, dataset: str | None = None) -> dict[str, Any]:
        """Статистика проверок."""
        if dataset:
            return {"dataset": dataset, **dict(self._stats[dataset])}
        return {k: dict(v) for k, v in self._stats.items()}
