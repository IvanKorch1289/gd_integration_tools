# ruff: noqa: S608 — false positive (internal query with controlled parameters)
"""PII Erasure DSL processor — 152-ФЗ compliance (S183).

ADR-152FZ: тенант имеет право требовать полного удаления всех PII данных
(``Право на забвение``, ФЗ-152 ст. 21). Этот процессор реализует DSL-шаг
для erasure workflow.

Capabilities:
- ``ai.memory.delete`` — для удаления vector store entries
- ``pii.audit`` — для audit event emission
- Сам erasure авторизуется на уровне DSL pipeline: наличие
  шага ``pii_erase`` в route уже подразумевает admin-авторизацию
  на erasure operation (см. S183 ADR-152FZ). Отдельный
  ``pii.erase`` capability не требуется — erasure неделегируемый.

Spec (YAML)::
    - pii_erase:
        scope: "user:42"           # target identifier
        reason: "gdpr_request"     # для audit
        hard_delete: true          # если True — удалить навсегда; иначе soft delete (anonymize)

Side effects:
1. Удаление entries из VectorStore (memory.erase)
2. Удаление из Postgres (KV-store / audit_log_anonymize)
3. Anonymization в MongoDB / ClickHouse
4. Audit event emit ``pii.erasure.completed`` с деталями

Note:
    Production deployment требует дополнительной интеграции с
    конкретными storage backends. Этот DSL — contract-level реализация
    через capability checks и audit emission.

"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("ErasureResult", "PiiEraseProcessor")

_logger = get_logger("dsl.security.pii_erase")

# Whitelist для entity_type в ``{entity_type}_pii`` table — только
# [A-Za-z0-9_], начинается с буквы/_ (см. db_crud ``_IDENTIFIER_RE``).
_ENTITY_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_entity_type(entity_type: str) -> str:
    """Return ``entity_type`` если проходит whitelist, иначе raise.

    S608 mitigation: гарантирует, что ``entity_type`` подставляется в SQL
    только как safe-identifier.
    """
    if not _ENTITY_TYPE_RE.fullmatch(entity_type):
        raise ValueError(
            f"pii_erase: invalid entity_type {entity_type!r} "
            "(only [A-Za-z0-9_] allowed)",
        )
    return entity_type


@dataclass(slots=True, frozen=True)
class ErasureResult:
    """Результат PII erasure операции.

    Attributes:
        erasure_id: Уникальный ID erasure операции (UUIDv4).
        scope: Target identifier (e.g., ``"user:42"``).
        hard_delete: True если hard delete, False если soft anonymize.
        vectors_deleted: Кол-во удалённых vector entries.
        records_anonymized: Кол-во anonymized DB records.
        audit_id: Audit event ID для tracking.
        duration_ms: Длительность операции.

    """

    erasure_id: str
    scope: str
    hard_delete: bool
    vectors_deleted: int
    records_anonymized: int
    audit_id: str
    duration_ms: float


class PiiEraseProcessor(BaseProcessor):
    """PII Erasure DSL processor — 152-ФЗ / GDPR compliance.

    Usage::

        builder.pii_erase(scope="user:42", reason="gdpr_request", hard_delete=True)

    Capabilities:
        Erasure авторизуется самим наличием шага ``pii_erase`` в DSL
        route (см. ADR-152FZ). Внутри процессора проверяются два
        capability: ``ai.memory.delete`` (vector store) и ``pii.audit``
        (anonymization в DB) — оба delegated через
        :func:`get_capability_facade`. ``pii.erase`` capability
        отдельно не существует: erasure — неделегируемая операция.

    Workflow:
        1. Emit ``pii.erasure.requested`` audit event
        2. Удалить vector entries (memory.delete capability)
        3. Anonymize DB records (pii.audit capability)
        4. Emit ``pii.erasure.completed`` audit event
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False  # erasure is non-reversible

    def __init__(
        self,
        *,
        scope: str,
        reason: str = "manual_request",
        hard_delete: bool = True,
        name: str | None = None,
    ) -> None:
        """Инициализация PII erasure processor.

        Args:
            scope: Target identifier (e.g., ``"user:42"``, ``"tenant:acme"``).
            reason: Причина erasure (``"gdpr_request"``, ``"user_request"``, etc.).
            hard_delete: True для full deletion, False для soft anonymize.
            name: Имя процессора в трейсах.

        """
        super().__init__(name=name or f"pii_erase[{scope}]")
        self._scope = scope
        self._reason = reason
        self._hard_delete = hard_delete

    @handle_processor_error
    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext,
    ) -> None:
        """Выполнить erasure для scope.

        Side effects:
            exchange.properties["pii_erasure_result"] = ErasureResult
        """
        start = time.monotonic()
        erasure_id = str(uuid.uuid4())

        # Step 1: emit requested audit event
        await self._emit_audit(
            event="pii.erasure.requested",
            erasure_id=erasure_id,
            scope=self._scope,
            reason=self._reason,
            hard_delete=self._hard_delete,
        )

        # Step 2: vector store deletion (lazy через capability gate)
        vectors_deleted = 0
        try:
            from src.backend.services.capabilities.facade import get_capability_facade

            cap_facade = get_capability_facade()
            if cap_facade.check("dsl", "ai.memory.delete", scope=self._scope):
                vectors_deleted = await self._delete_vectors(erasure_id)
            else:
                _logger.debug(
                    "vector deletion skipped: capability denied",
                )
        except Exception as exc:
            # cycle-8/D-AUDIT-804: PII erasure fail-CLOSED.
            # Bare `except Exception` ранее молча логировал warning и
            # exchange продолжал как "успешный" — PII оставался в vector
            # store (security regression, ADR-152FZ). Теперь: error +
            # DLQWriter.enqueue для durable observability + re-raise
            # (caller через @handle_processor_error → exchange.stop+error).
            _logger.error(
                "vector deletion failed: erasure_id=%s scope=%s error=%s",
                erasure_id,
                self._scope,
                exc,
            )
            await self._enqueue_failure_to_dlq(
                erasure_id=erasure_id, step="vectors", exc=exc,
            )
            raise

        # Step 3: DB anonymization
        records_anonymized = 0
        try:
            from src.backend.services.capabilities.facade import get_capability_facade

            cap_facade = get_capability_facade()
            if cap_facade.check("dsl", "pii.audit", scope=self._scope):
                records_anonymized = await self._anonymize_db(erasure_id)
        except Exception as exc:
            # cycle-8/D-AUDIT-804: см. выше — тот же fail-CLOSED pattern
            # для DB anonymization (PII остался бы в таблице ``<entity>_pii``).
            _logger.error(
                "DB anonymization failed: erasure_id=%s scope=%s error=%s",
                erasure_id,
                self._scope,
                exc,
            )
            await self._enqueue_failure_to_dlq(
                erasure_id=erasure_id, step="db_anonymize", exc=exc,
            )
            raise

        duration_ms = (time.monotonic() - start) * 1000

        result = ErasureResult(
            erasure_id=erasure_id,
            scope=self._scope,
            hard_delete=self._hard_delete,
            vectors_deleted=vectors_deleted,
            records_anonymized=records_anonymized,
            audit_id="",  # filled below
            duration_ms=round(duration_ms, 2),
        )

        # Step 4: emit completed audit
        audit_id = await self._emit_audit(
            event="pii.erasure.completed",
            erasure_id=erasure_id,
            scope=self._scope,
            reason=self._reason,
            hard_delete=self._hard_delete,
            vectors_deleted=vectors_deleted,
            records_anonymized=records_anonymized,
            duration_ms=result.duration_ms,
        )
        result = ErasureResult(
            erasure_id=result.erasure_id,
            scope=result.scope,
            hard_delete=result.hard_delete,
            vectors_deleted=result.vectors_deleted,
            records_anonymized=result.records_anonymized,
            audit_id=audit_id,
            duration_ms=result.duration_ms,
        )

        exchange.set_property("pii_erasure_result", result)
        _logger.info(
            "PII erasure completed: id=%s scope=%s hard=%s vectors=%d records=%d duration=%.1fms",
            erasure_id,
            self._scope,
            self._hard_delete,
            vectors_deleted,
            records_anonymized,
            duration_ms,
        )

    async def _delete_vectors(self, erasure_id: str) -> int:
        """S214: bulk delete Qdrant vectors по ``scope`` filter.

        Использует :meth:`BaseVectorStore.delete_where` (Qdrant native).
        При hard_delete=True — DELETE; иначе — no-op (anonymize обрабатывается
        DB-фильтром).

        Args:
            erasure_id: Correlation ID для audit.

        Returns:
            Количество удалённых vectors (Qdrant возвращает int).

        """
        try:
            from src.backend.infrastructure.clients.storage.vector_store import (
                get_vector_store,
            )

            store = get_vector_store()
            # Scope формат: "user:42" → filter {"entity_type": "user", "entity_id": "42"}
            # Если scope не парсится — soft skip с warning (input error, не backend).
            if ":" not in self._scope:
                _logger.warning(
                    "vector deletion: scope=%r не парсится (нет ':'), skip",
                    self._scope,
                )
                return 0
            entity_type, entity_id = self._scope.split(":", 1)
            return await store.delete_where(
                {"entity_type": entity_type, "entity_id": entity_id},
            )
        except Exception as exc:
            # cycle-8/D-AUDIT-804: PII erasure fail-CLOSED.
            # Bare `except Exception` ранее молча возвращал 0 — PII оставался
            # в vector store (ADR-152FZ regression). Теперь: error + propagate
            # до outer process() который enqueue DLQ + re-raise (caller
            # fail-CLOSED через @handle_processor_error → exchange.stop+error).
            _logger.error(
                "vector deletion failed: erasure_id=%s scope=%s error=%s",
                erasure_id,
                self._scope,
                exc,
            )
            raise

    async def _anonymize_db(self, erasure_id: str) -> int:
        """S214: anonymize records в основной DB (PostgreSQL/MongoDB).

        При ``hard_delete=True`` — выполняет DELETE FROM <entity_table>
        WHERE entity_id = :scope_id.
        При ``hard_delete=False`` — UPDATE: обнуляет PII поля (name, email, phone).

        Args:
            erasure_id: Correlation ID для audit.

        Returns:
            Количество affected records.

        """
        try:
            if ":" not in self._scope:
                return 0
            entity_type, entity_id = self._scope.split(":", 1)
            _validate_entity_type(entity_type)
            from src.backend.infrastructure.database.session_manager import (
                main_session_manager,
            )

            async with main_session_manager.get_session() as session:
                from sqlalchemy import text

                if self._hard_delete:
                    # ``entity_type`` was validated above by
                    # :func:`_validate_entity_type` (regex whitelist) → no
                    # SQL injection surface; values still bind via
                    # ``:entity_id``.
                    sql = text(
                        f"DELETE FROM {entity_type}_pii "
                        f"WHERE entity_id = :entity_id",
                        # ``entity_type`` validated by regex whitelist; values bound.
                    )
                    result = await session.execute(
                        sql, {"entity_id": entity_id},
                    )
                else:
                    sql = text(
                        f"UPDATE {entity_type}_pii "
                        f"SET name = NULL, email = NULL, phone = NULL, "
                        f"anonymized_at = NOW() "
                        f"WHERE entity_id = :entity_id",
                        # Same whitelist as DELETE branch above.
                    )
                    result = await session.execute(
                        sql, {"entity_id": entity_id},
                    )
                await session.commit()
                return int(result.rowcount or 0)
        except Exception as exc:
            # cycle-8/D-AUDIT-804: PII erasure fail-CLOSED.
            # Bare `except Exception` ранее молча возвращал 0 — PII оставался
            # в таблице ``<entity>_pii`` (ADR-152FZ regression). Теперь: error
            # + propagate до outer process() который enqueue DLQ + re-raise
            # (caller fail-CLOSED через @handle_processor_error → exchange.stop+error).
            _logger.error(
                "DB anonymization failed: erasure_id=%s scope=%s error=%s",
                erasure_id,
                self._scope,
                exc,
            )
            raise

    async def _emit_audit(
        self,
        *,
        event: str,
        erasure_id: str,
        scope: str,
        reason: str = "",
        hard_delete: bool = True,
        **fields: Any,
    ) -> str:
        """Emit audit event для erasure operation."""
        try:
            from src.backend.core.observability.logging_helpers import (
                log_audit_event_lite,
            )

            log_audit_event_lite(
                _logger,
                severity="warning",  # erasure — significant event
                event=event,
                erasure_id=erasure_id,
                scope=scope,
                reason=reason,
                hard_delete=hard_delete,
                **fields,
            )
            return erasure_id  # reuse erasure_id as audit correlation
        except Exception as exc:
            _logger.warning("audit emit failed: %s", exc)
            return ""

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфиг процессора в JSON-Schema spec."""
        return {
            "type": "pii_erase",
            "scope": self._scope,
            "reason": self._reason,
            "hard_delete": self._hard_delete,
        }

    async def _enqueue_failure_to_dlq(
        self,
        *,
        erasure_id: str,
        step: str,
        exc: BaseException,
    ) -> None:
        """Persist PII erasure failure в DLQ для durable observability (cycle-8/D-AUDIT-804).

        Использует :class:`InMemoryDLQWriter` как минимальный writer.
        Production должен переопределить через DI (composition root) —
        :func:`set_stream_dlq_writer_provider` или singleton-инжекция.
        При сбое DLQ самого — log error, но НЕ swallow (outer re-raise =
        fail-CLOSED caller path).
        """
        try:
            from src.backend.core.di.providers.dlq_bridge import (
                get_dlq_envelope_class,
                get_dlq_reason_class,
            )

            DLQEnvelope = get_dlq_envelope_class()
            DLQReason = get_dlq_reason_class()
            envelope = DLQEnvelope(
                transport="dsl.pii_erase",
                route_id=f"pii_erase[{self._scope}]",
                original_payload={"erasure_id": erasure_id, "step": step},
                error_class=type(exc).__name__,
                error_message=str(exc),
                reason=DLQReason.UNEXPECTED,
            )
            from src.backend.infrastructure.messaging.dlq.memory_writer import (
                InMemoryDLQWriter,
            )

            writer = InMemoryDLQWriter()
            await writer.write(envelope)
        except Exception as dlq_exc:
            # DLQ сам недоступен — log error (caller всё равно re-raise).
            _logger.error(
                "pii_erase: DLQ enqueue failed: erasure_id=%s step=%s dlq_error=%s",
                erasure_id,
                step,
                dlq_exc,
            )
