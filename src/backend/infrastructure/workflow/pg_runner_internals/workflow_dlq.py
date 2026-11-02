"""DLQ-контракт для исчерпавших попыток шагов workflow (ADR-0408).

Исчерпание retry-бюджета шага переводит workflow в терминальный
``FAILED``, но до волны 22 исчерпанный шаг нигде не оставался: разбирать
его было негде. Контракт ADR-0408 — исчерпанный шаг попадает в
**существующий** messaging-DLQ (:mod:`src.backend.infrastructure.messaging.dlq_base`):
тот же ``DLQEnvelope``/``DLQWriter``, что и для HTTP/SOAP/gRPC-транспортов,
с ``transport="workflow"``.

Что попадает в запись:

* ``route_id`` / ``tenant_id`` — из строки workflow-инстанса;
* ``step`` / ``attempts`` / ``max_attempts`` — по исчерпавшемуся шагу;
* ``reason`` — ``DLQReason.RETRIES_EXHAUSTED``;
* ``metadata.payload_keys`` — **имена** ключей входного payload'а.

Значения данных workflow в DLQ **не** попадают (``original_payload=None``):
DLQ — сигнал о потерянном шаге, а не его архив.

Идемпотентность: ``dlq_id`` детерминирован (``sha256(instance|step|attempt)``
— тот же ключ, что у идемпотентности шага в event log'е), поэтому
повторный запуск того же шага не создаёт вторую запись: writers с
``ON CONFLICT (dlq_id) DO NOTHING`` (``InboxDLQWriter``) отсекают дубль на
уровне БД, а publisher дополнительно гасит повтор в рамках процесса.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.backend.core.logging import get_logger
from src.backend.core.observability.workflow_sla import record_workflow_dlq_publish
from src.backend.infrastructure.messaging.dlq_base import (
    DLQEnvelope,
    DLQReason,
    DLQWriter,
)
from src.backend.infrastructure.workflow.pg_runner_internals.rows import (
    WorkflowInstanceRow,
)

__all__ = (
    "WORKFLOW_DLQ_TRANSPORT",
    "WorkflowDLQPublisher",
    "build_exhausted_step_envelope",
)

_logger = get_logger("workflow.dlq")

WORKFLOW_DLQ_TRANSPORT = "workflow"
"""Transport-имя DLQ-записи для исчерпанных шагов workflow (``dlq.workflow``)."""

_ERROR_CLASS = "RetryBudgetExhausted"
"""Класс ошибки по умолчанию — retry-бюджет шага исчерпан."""

_MESSAGE_LIMIT = 2000
"""Ограничение длины сообщения об ошибке в DLQ-записи."""


def build_exhausted_step_envelope(
    *,
    dlq_id: str,
    instance: WorkflowInstanceRow,
    step_name: str,
    attempts: int,
    max_attempts: int,
    error_message: str | None,
    error_class: str = _ERROR_CLASS,
    payload_keys: Sequence[str] = (),
) -> DLQEnvelope:
    """Собрать DLQ-envelope исчерпанного шага workflow.

    Args:
        dlq_id: Детерминированный id записи (см. ``runner.idempotency_key``).
        instance: Row workflow-инстанса (route_id / tenant_id / payload).
        step_name: Имя исчерпавшегося шага.
        attempts: Номер последней попытки.
        max_attempts: Размер retry-бюджета шага.
        error_message: Текст ошибки шага (``None`` — дефолтный).
        error_class: Имя класса ошибки в DLQ-записи.
        payload_keys: Имена ключей входного payload'а (без значений).

    Returns:
        Готовый :class:`DLQEnvelope` (значения данных не содержатся).

    """
    message = (error_message or "workflow step retry budget exhausted")[:_MESSAGE_LIMIT]
    return DLQEnvelope(
        dlq_id=dlq_id,
        transport=WORKFLOW_DLQ_TRANSPORT,
        tenant_id=instance.tenant_id or None,
        route_id=instance.route_id or None,
        original_payload=None,
        error_class=error_class,
        error_message=message,
        reason=DLQReason.RETRIES_EXHAUSTED,
        retry_count=attempts,
        metadata={
            "workflow_id": str(instance.id),
            "workflow_name": instance.workflow_name,
            "step": step_name,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "reason": "max_attempts_exceeded",
            "payload_keys": list(payload_keys),
        },
    )


class WorkflowDLQPublisher:
    """Публикация исчерпанных шагов workflow в messaging-DLQ.

    Args:
        writer: ``DLQWriter`` (canonical writer из composition root).
            ``None`` — публикация пропускается (fail-loud: warning-лог +
            метрика ``workflow_dlq_publish_total{status="no_writer"}``),
            workflow при этом не падает.

    """

    def __init__(self, writer: DLQWriter | None = None) -> None:
        self._writer = writer
        self._seen: set[str] = set()

    @property
    def writer(self) -> DLQWriter | None:
        """Writer, в который публикуются записи (``None`` — не настроен)."""
        return self._writer

    async def publish_exhausted_step(
        self,
        *,
        dlq_id: str,
        instance: WorkflowInstanceRow,
        step_name: str,
        attempts: int,
        max_attempts: int,
        error_message: str | None,
        payload_keys: Sequence[str] = (),
    ) -> bool:
        """Опубликовать исчерпанный шаг в DLQ.

        Args:
            dlq_id: Детерминированный id записи (источник идемпотентности).
            instance: Row workflow-инстанса.
            step_name: Имя исчерпавшегося шага.
            attempts: Номер последней попытки.
            max_attempts: Размер retry-бюджета шага.
            error_message: Текст ошибки шага.
            payload_keys: Имена ключей входного payload'а (без значений).

        Returns:
            ``True`` — запись опубликована; ``False`` — пропущена (writer
            не настроен, дубль по ``dlq_id`` или ошибка записи).

        """
        if self._writer is None:
            record_workflow_dlq_publish("no_writer")
            _logger.warning(
                "workflow.dlq.writer_not_configured",
                extra={
                    "workflow_id": str(instance.id),
                    "route_id": instance.route_id,
                    "step": step_name,
                },
            )
            return False
        if dlq_id in self._seen:
            record_workflow_dlq_publish("duplicate")
            return False
        envelope = build_exhausted_step_envelope(
            dlq_id=dlq_id,
            instance=instance,
            step_name=step_name,
            attempts=attempts,
            max_attempts=max_attempts,
            error_message=error_message,
            payload_keys=payload_keys,
        )
        try:
            await self._writer.write(envelope)
        except Exception as exc:
            record_workflow_dlq_publish("error")
            _logger.error(
                "workflow.dlq.write_failed: %s",
                exc,
                extra={
                    "dlq_id": dlq_id,
                    "workflow_id": str(instance.id),
                    "route_id": instance.route_id,
                    "step": step_name,
                },
            )
            return False
        self._seen.add(dlq_id)
        record_workflow_dlq_publish("published")
        _logger.warning(
            "workflow.dlq.step_exhausted",
            extra={
                "dlq_id": dlq_id,
                "workflow_id": str(instance.id),
                "route_id": instance.route_id,
                "step": step_name,
                "attempts": attempts,
                "max_attempts": max_attempts,
            },
        )
        return True
