from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # cycle-8/D-AUDIT-803: canonical DQ types live in __init__.py
    pass

"""Data Quality Monitor — авто-детект схемы + аномалии.

Проверки:
- Missing required fields (NULL/empty)
- Type violations (string in numeric field)
- Outliers (Z-score > 3σ)
- Duplicate records (same PK within window)
- Late-arriving data (> threshold old)
- Schema drift (новые/удалённые поля)

Actions: dq.check, dq.schema_infer, dq.stats, dq.rules

cycle-8/D-AUDIT-803: DQSeverity/DQViolation/DQCheckResult/DQRule consolidated
в __init__.py (canonical). Здесь только runtime use через post-load injection
(см. __init__.py).
"""

from collections import defaultdict


from src.backend.services.ops.data_quality._protocol import _DataQualityProtocol


class SchemaMixin(_DataQualityProtocol):
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
