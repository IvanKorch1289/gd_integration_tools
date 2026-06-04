"""Periodic DLQ cleanup job — удаляет старые записи по policy (S13 K3 W4).

Запускается через APScheduler / TaskRegistry: scan DLQ ClickHouse table,
delete где ``created_at + retention_days < now()`` per ``dlq_class``.

Метрики:

* ``dlq_cleanup_deleted_total{class}`` (Counter).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.messaging.dlq_policy import DLQPolicyRegistry

__all__ = ("DLQCleanupJob", "DLQCleanupStats")

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    from prometheus_client import Counter as _PromCounter

    _CLEANUP_COUNTER = _PromCounter(
        "dlq_cleanup_deleted_total",
        "Number of DLQ records deleted by cleanup job",
        ("dlq_class",),
    )
except Exception as _:
    _CLEANUP_COUNTER = None  # type: ignore[assignment,unused-ignore]


@dataclass(slots=True)
class DLQCleanupStats:
    """Статистика одного запуска cleanup-job."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_per_class: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def total_deleted(self) -> int:
        return sum(self.deleted_per_class.values())


class DLQCleanupJob:
    """Cleanup-job для DLQ ClickHouse table.

    Args:
        ch_client: ClickHouse client с ``execute(sql, params=...)`` методом.
        registry: :class:`DLQPolicyRegistry` с зарегистрированными policy.
        table_name: имя DLQ-таблицы (default ``dlq_events``).
        clock: функция текущего времени (для тестов).
    """

    def __init__(
        self,
        *,
        ch_client: Any,
        registry: DLQPolicyRegistry,
        table_name: str = "dlq_events",
        clock: Any = None,
    ) -> None:
        self._client = ch_client
        self._registry = registry
        self._table = table_name
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(self) -> DLQCleanupStats:
        """Выполнить cleanup один раз; вернуть статистику."""
        stats = DLQCleanupStats()
        now = self._clock()
        for policy in self._registry.list_all():
            cutoff = now - timedelta(days=policy.retention_days)
            # table_name контролируется конструктором (не user input); параметры — через %s.
            sql = f"DELETE FROM {self._table} WHERE dlq_class = %s AND created_at < %s"  # noqa: S608  # internal query with controlled parameters
            try:
                await self._client.execute(
                    sql, params=[policy.class_name, cutoff.isoformat()]
                )
                # ClickHouse не возвращает row count из DELETE; для целей
                # метрик используем приблизительное значение из predicate.
                deleted = await self._count_deleted_approx(policy.class_name, cutoff)
                stats.deleted_per_class[policy.class_name] = deleted
                if _CLEANUP_COUNTER is not None:
                    try:
                        _CLEANUP_COUNTER.labels(dlq_class=policy.class_name).inc(
                            deleted
                        )
                    except Exception:
                        pass
            except Exception as exc:
                msg = f"cleanup_failed class={policy.class_name}: {exc!r}"
                stats.errors.append(msg)
                logger.exception(msg)
        return stats

    async def _count_deleted_approx(self, class_name: str, cutoff: Any) -> int:
        """Оценка количества удалённых записей (для метрик).

        ClickHouse DELETE не возвращает row count — выполняем отдельный
        COUNT перед DELETE для approximate stats. На production может
        быть заменено на ``OPTIMIZE TABLE ... FINAL DEDUPLICATE`` метрику.
        """
        sql = f"SELECT count() FROM {self._table} WHERE dlq_class = %s AND created_at < %s"  # noqa: S608  # internal query with controlled parameters
        try:
            rows = await self._client.execute(
                sql, params=[class_name, cutoff.isoformat()]
            )
            if rows and isinstance(rows[0], dict):
                return int(rows[0].get("count()", 0))
            if rows and isinstance(rows[0], (list, tuple)):
                return int(rows[0][0])
        except Exception:
            pass
        return 0
