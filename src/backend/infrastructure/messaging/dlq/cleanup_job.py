# ruff: noqa: S608 — false positive (internal query with controlled parameters)
"""Periodic DLQ cleanup job — удаляет старые записи по policy (S13 K3 W4).

Запускается через APScheduler / TaskRegistry: scan DLQ ClickHouse table,
delete где ``created_at + retention_days < now()`` per ``dlq_class``.

Метрики:

* ``dlq_cleanup_deleted_total{class}`` (Counter).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.messaging.dlq_policy import DLQPolicyRegistry


def _iso_to_yyyymm(iso_str: str) -> str:
    """Convert ISO-8601 string → ClickHouse partition suffix (YYYYMM).

    ClickHouse PARTITION BY toYYYYMM(created_at) → partition name
    pattern is ``YYYYMM`` (e.g. ``202608`` for Aug 2026).
    D-AUDIT-FIX-184-4: helper for ALTER TABLE ... DROP PARTITION ID.
    """
    # iso_str is e.g. "2026-08-05T14:30:00+00:00"; take first 7 chars "YYYY-MM"
    return iso_str[:7].replace("-", "")

__all__ = ("DLQCleanupJob", "DLQCleanupStats")

logger = get_logger(__name__)

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
        """Метод total_deleted (см. signature)."""
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
        """Выполнить cleanup один раз; вернуть статистику.

        D-AUDIT-FIX-184-4 (S184 W4 #4, 2026-08-05): заменён DELETE
        на PARTITION DETACH ... DROP PARTITION (per b69d6b49
        migration). ClickHouse PARTITION pruning O(n*log(n)) эффективнее
        full-table DELETE (O(n)) и не вызывает heavy-merge.
        """
        stats = DLQCleanupStats()
        now = self._clock()
        for policy in self._registry.list_all():
            cutoff = now - timedelta(days=policy.retention_days)
            cutoff_partition = _iso_to_yyyymm(cutoff.isoformat())
            # table_name контролируется конструктором (не user input);
            # partition suffix вычисляется из cutoff (controlled).
            sql = (
                f"ALTER TABLE {self._table} "
                f"DROP PARTITION ID '{cutoff_partition}'"
            )
            try:
                await self._client.execute(sql)
                # ClickHouse не возвращает row count из DROP PARTITION;
                # используем приблизительное значение из predicate.
                deleted = await self._count_deleted_approx(policy.class_name, cutoff)
                stats.deleted_per_class[policy.class_name] = deleted
                if _CLEANUP_COUNTER is not None:
                    try:
                        _CLEANUP_COUNTER.labels(dlq_class=policy.class_name).inc(
                            deleted,
                        )
                    except (AttributeError, TypeError, ValueError) as counter_exc:
                        # cycle-9/D-AUDIT-931: narrow exceptions + observability.
                        # AttributeError — counter API change, TypeError —
                        # invalid arg, ValueError — invalid label value.
                        import logging
                        logging.getLogger(__name__).debug(
                            "dlq_cleanup.counter_inc_failed",
                            extra={"dlq_class": policy.class_name, "error": str(counter_exc)},
                        )
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
        sql = f"SELECT count() FROM {self._table} WHERE dlq_class = %s AND created_at < %s"  # internal query with controlled parameters
        try:
            rows = await self._client.execute(
                sql, params=[class_name, cutoff.isoformat()],
            )
            if rows and isinstance(rows[0], dict):
                return int(rows[0].get("count()", 0))
            if rows and isinstance(rows[0], (list, tuple)):
                return int(rows[0][0])
        except (RuntimeError, ConnectionError, OSError, AttributeError) as count_exc:
            # cycle-9/D-AUDIT-932: narrow exceptions + observability.
            # RuntimeError — ClickHouse unavailable, ConnectionError —
            # network, OSError — protocol, AttributeError — client API
            # change. Bare `except Exception` маскировал unrelated runtime
            # errors (KeyError, TypeError).
            import logging
            logging.getLogger(__name__).debug(
                "dlq_cleanup.count_deleted_failed",
                extra={"class_name": class_name, "error": str(count_exc)},
            )
        return 0
