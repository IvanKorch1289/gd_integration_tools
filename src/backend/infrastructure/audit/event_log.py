# ruff: noqa: S608 — false positive (internal query with controlled parameters)
"""Audit Event Log — кто/что/когда → ClickHouse через AsyncBatcher.

M4 note: secondary ES-индексация через ``log_indexer`` (см. ``flush()``)
— best-effort fallback. **DO NOT** use both
:mod:`core.audit.facade.audit_service` (canonical) and this module
for the same event — you will double-write to ClickHouse. This
module is the batch/bulk-write path used by
:mod:`core.audit.facade._base` fan-out helpers and
:mod:`services.audit.workflow_audit_sink`. Per-event emit goes via
:func:`core.audit.facade.audit_service.emit` instead.

B-25 fix (cycle 1): при сбое ClickHouse client'а failed-events
роутятся в DLQ через ``DLQWriter`` Protocol (аналогично
:class:`~src.backend.infrastructure.clients.external.cdc.client.CDCClient`).
Без writer'а в production поднимается ``RuntimeError`` (fail-loud,
mirror ``mark_cdc_dlq_writer_wired`` pattern из cycle 37).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces import AsyncBatcher
from src.backend.core.logging import get_logger
from src.backend.infrastructure.observability.correlation import (
    get_correlation_id,
    get_tenant_id,
)

# S44 W5: facade import через core.observability (was string-bypass
# dynamic import 'src.backend.services.io.indexers.log_indexer' чтобы
# обойти static AST layer linter). Теперь прямой static import.

if TYPE_CHECKING:
    from src.backend.infrastructure.messaging.dlq_base import DLQWriter

__all__ = ("AuditEvent", "AuditEventLog", "emit_audit_event", "get_audit_log")

logger = get_logger(__name__)


@dataclass(slots=True)
class AuditEvent:
    """Метод AuditEvent (см. signature)."""

    who: str
    what: str
    entity_type: str
    entity_id: str
    action: str
    when: datetime = field(default_factory=lambda: datetime.now(UTC))
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    correlation_id: str = ""
    tenant_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditEventLog:
    """Записывает audit events в ClickHouse через batch insert.

    B-25 fix (cycle 1): DLQ wiring.

    При сбое ``client.insert()`` в ``_flush_to_clickhouse`` failed-events
    сериализуются в :class:`DLQEnvelope` и пишутся через настроенный
    ``DLQWriter``. Без writer'а:

    * production (``dlq_required=True``, default) — ``RuntimeError``
      (fail-loud, как ``mark_cdc_dlq_writer_wired``);
    * dev_light / tests (``dlq_required=False``) — log+drop, не raise.
    """

    def __init__(
        self,
        table: str = "audit_events",
        batch_size: int = 50,
        *,
        dlq_writer: DLQWriter | None = None,
        dlq_required: bool = True,
    ) -> None:
        """Инициализирует AuditEventLog.

        Args:
            table: имя таблицы ClickHouse (allowlist: ``audit_events`` /
                ``audit_log`` enforced только в ``query``).
            batch_size: размер батча для AsyncBatcher.
            dlq_writer: [B-25 fix (cycle 1)] ``DLQWriter`` для
                failed-events при сбое ClickHouse. Устанавливается
                post-init через :meth:`set_dlq_writer` из composition
                root (для singleton-friendly pattern, см. CDCClient).
            dlq_required: [B-25 fix (cycle 1)] production-guard.
                Если ``True`` (default) и writer не сконфигурирован —
                ``_send_to_dlq`` поднимет ``RuntimeError`` (fail-loud).
                В dev_light / unit-tests выставляется ``False`` через
                :meth:`set_dlq_required` или напрямую.

        """
        self._table = table
        # B-25 fix (cycle 1): DLQ handoff на сбое ClickHouse client.
        self._dlq_writer: DLQWriter | None = dlq_writer
        self._dlq_required: bool = dlq_required
        self._batcher = AsyncBatcher(
            flush_fn=self._flush_to_clickhouse,
            batch_size=batch_size,
            flush_interval_seconds=5.0,
        )

    def set_dlq_writer(self, writer: DLQWriter | None) -> None:
        """Установить/сбросить DLQ-writer (для composition root wiring).

        B-25 fix (cycle 1): singleton :func:`get_audit_log` не имеет
        доступа к ``__init__``-аргументам; этот setter позволяет
        composition root подключить InboxDLQWriter/KafkaDLQWriter/etc.
        пост-фактум (тот же паттерн, что
        :meth:`CDCClient.set_dlq_writer` из S176 cycle 33).
        """
        self._dlq_writer = writer

    def set_dlq_required(self, required: bool) -> None:
        """Override ``dlq_required`` (для dev_light / tests).

        B-25 fix (cycle 1): production default ``True`` (fail-loud);
        ``DLQSettings``/profile в dev_light выставляет ``False``.
        """
        self._dlq_required = required

    async def start(self) -> None:
        """Метод start (см. signature)."""
        await self._batcher.start()
        logger.info("AuditEventLog started (table=%s)", self._table)

    async def stop(self) -> None:
        """Метод stop (см. signature)."""
        await self._batcher.stop()
        logger.info("AuditEventLog stopped")

    async def emit(self, event: AuditEvent) -> None:
        """Emit an audit event.

        Args:
            event: Audit event to emit.

        """
        if not event.correlation_id:
            event.correlation_id = get_correlation_id()
        if not event.tenant_id:
            event.tenant_id = get_tenant_id()
        await self._batcher.add(event)

    async def _flush_to_clickhouse(self, events: list[AuditEvent]) -> None:
        try:
            from src.backend.infrastructure.clients.storage.clickhouse import (
                get_clickhouse_client,
            )

            client = get_clickhouse_client()
            rows = []
            from src.backend.infrastructure.audit._json_codec import dumps_str

            for e in events:
                rows.append(
                    {
                        "who": e.who,
                        "what": e.what,
                        "entity_type": e.entity_type,
                        "entity_id": e.entity_id,
                        "action": e.action,
                        "when": e.when.isoformat(),
                        "before_data": dumps_str(e.before) if e.before else "",
                        "after_data": dumps_str(e.after) if e.after else "",
                        "correlation_id": e.correlation_id,
                        "tenant_id": e.tenant_id,
                        "metadata": dumps_str(e.metadata),
                    },
                )
            await client.insert(self._table, rows)
            logger.debug("Flushed %d audit events to ClickHouse", len(rows))
        except Exception as exc:
            # B-25 fix (cycle 1): silent-loss был P0 — failed-events
            # теперь роутятся в DLQ через _send_to_dlq (production
            # fail-loud при отсутствии writer'а). Лог сохранён для
            # обратной совместимости с существующими дашбордами.
            logger.error("Audit flush to ClickHouse failed: %s", exc)
            await self._send_to_dlq(events, exc)

        # Wave 9.3.1: secondary indexing в Elasticsearch (best-effort).
        # S44 W5: facade import через core.observability (was string-bypass).
        # B-25 fix (cycle 1) scope: только ClickHouse-failure path; ES —
        # secondary best-effort, оставляем log+drop (известное поведение).
        try:
            from src.backend.core.observability.log_indexer import get_log_indexer

            indexer = get_log_indexer()
            await indexer.index_batch(events)
        except Exception as es_exc:
            logger.warning("LogIndexer.index_batch failed: %s", es_exc)

    async def _send_to_dlq(
        self,
        events: list[AuditEvent],
        exc: BaseException,
    ) -> None:
        """Отправить failed-events в DLQ (B-25 fix (cycle 1)).

        Зеркалит :meth:`CDCClient._send_to_dlq` (S176 cycle 33 B-02 +
        S180 cycle 37 B-17 fail-loud guard):

        1. ``writer is None`` + ``_dlq_required=True`` → ``RuntimeError``
           (production fail-loud, аналог ``mark_cdc_dlq_writer_wired``).
        2. ``writer is None`` + ``_dlq_required=False`` → log+drop
           (dev_light / unit-tests).
        3. ``writer`` сконфигурирован → :class:`DLQEnvelope` per event
           + ``await writer.write(envelope)``. Failure DLQ-записи логируется
           на ``exc_info`` и не пробрасывается (consumer-loop не должен
           падать из-за observability-сбоя).

        Args:
            events: батч событий, не доехавший в ClickHouse.
            exc: исключение от ClickHouse client'а (для envelope metadata).

        Raises:
            RuntimeError: только в production-mode без writer'а.

        """
        if self._dlq_writer is None:
            if self._dlq_required:
                # B-25 fix (cycle 1): production fail-loud (analog CDCClient).
                msg = (
                    f"Audit events dropped: DLQ writer not wired "
                    f"[count={len(events)}, table={self._table}, "
                    f"error={type(exc).__name__}: {exc}]"
                )
                logger.error(msg)
                raise RuntimeError(msg)
            # B-25 fix (cycle 1): dev_light / unit-tests — log+drop.
            logger.warning(
                "Audit no DLQ writer configured; dropping events silently "
                "(dev_light) [count=%d, error=%s]",
                len(events),
                type(exc).__name__,
            )
            return

        # B-25 fix (cycle 1): build DLQ envelopes.
        envelopes = self._build_dlq_envelopes(events, exc)
        if not envelopes:
            return

        # B-25 fix (cycle 1): write каскадно, fail-each отдельно,
        # чтобы падение одного envelope не теряло остальные.
        for env in envelopes:
            try:
                await self._dlq_writer.write(env)
            except Exception as dlq_exc:
                logger.exception(
                    "Audit DLQ handoff failed [dlq_id=%s, tenant=%s]: %s "
                    "— EVENT WILL BE LOST",
                    env.dlq_id,
                    env.tenant_id,
                    dlq_exc,
                )
                # Не пробрасываем: audit-middleware не должен падать
                # из-за DLQ-сбоя (fire-and-forget semantics как в
                # ClickHouseAuditService._send_to_dlq).
                continue
        logger.warning(
            "Audit events forwarded to DLQ after ClickHouse failure "
            "[count=%d, table=%s]",
            len(envelopes),
            self._table,
        )

    def _build_dlq_envelopes(
        self,
        events: list[AuditEvent],
        exc: BaseException,
    ) -> list[Any]:
        """Строит :class:`DLQEnvelope` список для batch'а.

        B-25 fix (cycle 1): lazy import ``DLQEnvelope`` / ``DLQReason``
        чтобы избежать циклической зависимости с messaging-слоем на
        import-time (mirror CDCClient._send_to_dlq).

        Returns:
            Список envelopes; пустой список если build упал.

        """
        try:
            from src.backend.infrastructure.messaging.dlq_base import (  # noqa: F401 — availability probe
                DLQEnvelope,
                DLQReason,
            )
        except ImportError:  # pragma: no cover -- defensive
            logger.exception("DLQ base import failed; cannot build envelopes")
            return []

        envelopes: list[Any] = []
        error_class = type(exc).__name__
        error_message = f"clickhouse flush failed: {exc}"
        for e in events:
            try:
                envelopes.append(
                    DLQEnvelope(
                        transport="audit_event_log",
                        trace_id=e.correlation_id or None,
                        tenant_id=e.tenant_id or None,
                        route_id=e.entity_type or None,
                        original_payload={
                            "who": e.who,
                            "what": e.what,
                            "entity_type": e.entity_type,
                            "entity_id": e.entity_id,
                            "action": e.action,
                            "when": e.when.isoformat(),
                            "before": e.before,
                            "after": e.after,
                            "correlation_id": e.correlation_id,
                            "tenant_id": e.tenant_id,
                            "metadata": dict(e.metadata),
                        },
                        error_class=error_class,
                        error_message=error_message,
                        reason=DLQReason.UNEXPECTED,
                        metadata={
                            "table": self._table,
                            "batch_size": len(events),
                        },
                        dlq_class="operational",
                    ),
                )
            except Exception as build_exc:
                # Envelope build failed (should not happen, defensive):
                # log + drop, never propagate.
                logger.exception(
                    "Audit DLQ envelope build failed "
                    "[who=%s, entity_id=%s]: %s",
                    e.who,
                    e.entity_id,
                    build_exc,
                )
        return envelopes

    async def query(
        self,
        entity_type: str | None = None,
        entity_id: str | None = None,
        who: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """SELECT с фильтрами для audit_events / audit_log.

        ponytail: S61 W4 defense-in-depth был заменён на полноценные
        bound parameters через ClickHouse {name} syntax вместо _escape().
        ClickHouse HTTP API поддерживает {name} placeholders, которые
        корректно экранируются на уровне протокола.

        Защита от SQL injection:
        1. _safe_ident — allowlist для table name (audit_events / audit_log)
        2. Bound parameters через ClickHouse {name} syntax
        3. safe_limit — int(limit) bounded к [1, 10000]
        """
        from src.backend.infrastructure.clients.storage.clickhouse import (
            get_clickhouse_client,
        )

        client = get_clickhouse_client()

        def _safe_ident(name: str, allowed: set[str]) -> str:
            """Allowlist validation для table name."""
            if name not in allowed:
                raise ValueError(f"Invalid identifier: {name}")
            return name

        # Валидация table name через allowlist
        safe_table = _safe_ident(self._table, {"audit_events", "audit_log"})

        # Валидация limit (int, bounded)
        try:
            safe_limit = max(1, min(int(limit), 10000))
        except (TypeError, ValueError):
            safe_limit = 100

        # Build query с bound parameters через {name} syntax
        params: dict[str, Any] = {}
        conditions = []

        if entity_type:
            params["entity_type"] = entity_type
            conditions.append("entity_type = {entity_type:String}")
        if entity_id:
            params["entity_id"] = entity_id
            conditions.append("entity_id = {entity_id:String}")
        if who:
            params["who"] = who
            conditions.append("who = {who:String}")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM {safe_table}{where} ORDER BY when DESC LIMIT {safe_limit}"
        return await client.query(sql, params)


_audit_log: AuditEventLog | None = None


def get_audit_log() -> AuditEventLog:
    """Возвращает singleton :class:`AuditEventLog` (lazy init)."""
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditEventLog()
    return _audit_log


async def emit_audit_event(
    who: str,
    what: str,
    entity_type: str,
    entity_id: str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    **metadata: Any,
) -> None:
    """Создаёт :class:`AuditEvent` и публикует через singleton ``get_audit_log()``."""
    event = AuditEvent(
        who=who,
        what=what,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
        metadata=metadata,
    )
    await get_audit_log().emit(event)
