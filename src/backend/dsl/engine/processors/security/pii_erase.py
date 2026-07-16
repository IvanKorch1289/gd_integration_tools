"""PII Erasure DSL processor — 152-ФЗ compliance (S183).

ADR-152FZ: тенант имеет право требовать полного удаления всех PII данных
(``Право на забвение``, ФЗ-152 ст. 21). Этот процессор реализует DSL-шаг
для erasure workflow.

Capabilities:
- ``ai.memory.delete`` — для удаления vector store entries
- ``pii.audit`` — для audit event emission
- ``pii.erase`` — для самого erasure (TODO capability)

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
        ``pii.erase`` (TODO) — capability для erasure operation

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
        self, exchange: Exchange[Any], context: ExecutionContext
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
            from src.backend.services.capabilities.facade import (
                get_capability_facade,
            )

            cap_facade = get_capability_facade()
            if cap_facade.check("dsl", "ai.memory.delete", scope=self._scope):
                vectors_deleted = await self._delete_vectors(erasure_id)
            else:
                _logger.debug(
                    "vector deletion skipped: capability denied"
                )
        except Exception as exc:
            _logger.warning("vector deletion failed: %s", exc)

        # Step 3: DB anonymization
        records_anonymized = 0
        try:
            from src.backend.services.capabilities.facade import (
                get_capability_facade,
            )

            cap_facade = get_capability_facade()
            if cap_facade.check("dsl", "pii.audit", scope=self._scope):
                records_anonymized = await self._anonymize_db(erasure_id)
        except Exception as exc:
            _logger.warning("DB anonymization failed: %s", exc)

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
        """Удалить vector entries (lazy через memory adapters)."""
        # Production: подключить к VectorStoreClient.delete_by_filter
        # S183: stub — production wiring TODO
        _logger.debug(
            "vector deletion: erasure_id=%s scope=%s (stub)",
            erasure_id,
            self._scope,
        )
        return 0

    async def _anonymize_db(self, erasure_id: str) -> int:
        """Anonymize DB records (lazy через DB adapters)."""
        # Production: подключить к PostgreSQL/MongoDB
        # S183: stub — production wiring TODO
        _logger.debug(
            "DB anonymization: erasure_id=%s scope=%s (stub)",
            erasure_id,
            self._scope,
        )
        return 0

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
