"""HITL-approval processor — human-in-the-loop через HitlService.

Wave: ``[wave:s8/k4-hitl-approval]``. Этот процессор реализует паттерн
Human-in-the-Loop для DSL pipeline с использованием HitlService:
1. Приостанавливает pipeline, регистрирует pending signal в HitlService
2. Ожидает решения от оператора (approve/reject/request_info)
3. Возобновляет pipeline на основе решения

В отличие от generic :class:`HumanApprovalProcessor` (business.py),
этот процессор работает с :class:`HitlService` и :class:`HitlSignalStore`,
используя Temporal signal-based workflow pause.

Использование (Python builder)::

    from src.backend.services.workflows.hitl_service import HitlService

    hitl_service = HitlService(store=hitl_store)

    builder.hitl_approval(
        hitl_service=hitl_service,
        title="Подтвердите перевод 50000 RUB",
        approvers=["manager@bank.ru"],
        timeout_seconds=3600,
    )

YAML (blueprint)::

    - hitl_approval:
        title: "Подтвердите перевод"
        approvers:
          - manager@bank.ru
        timeout_seconds: 3600
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.services.workflows.hitl_service import HitlService

__all__ = ("HitlApprovalProcessor",)

_logger = get_logger("dsl.hitl_approval")


class HitlApprovalProcessor(BaseProcessor):
    """HITL-approval через HitlService.

    Приостанавливает pipeline, регистрирует pending signal в HitlService,
    ожидает решения от оператора и возобновляет pipeline.

    Args:
        hitl_service: Экземпляр :class:`HitlService` для регистрации/ожидания.
        title: Заголовок запроса (отображается оператору).
        description: Описание запроса.
        approvers: Список user-id, которым направляется уведомление.
            Пустой список = уведомление всем операторам.
        timeout_seconds: Максимальное время ожидания решения.
            По умолчанию 24 часа.
        payload_path: JMESPath к данным в body для формирования payload.
            Если None — весь body используется как payload.
        request_info_processors: Опциональные процессоры для выполнения
            при action=request_info (оператор запрашивает дополнительные данные).
    """

    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = False

    def __init__(
        self,
        hitl_service: HitlService,
        *,
        title: str,
        description: str = "",
        approvers: list[str] | None = None,
        timeout_seconds: float = 86_400.0,
        payload_path: str | None = None,
        request_info_processors: list[BaseProcessor] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "hitl_approval")
        self._hitl_service = hitl_service
        self._title = title
        self._description = description
        self._approvers = approvers or []
        self._timeout = timeout_seconds
        self._payload_path = payload_path
        self._request_info_processors = request_info_processors or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        signal_id = str(uuid.uuid4())

        # Извлекаем tenant_id из exchange properties или заголовков
        tenant_id = exchange.properties.get("tenant_id")
        if not tenant_id:
            tenant_id = exchange.in_message.headers.get("x-tenant-id", "default")

        # Извлекаем workflow_id из context или создаём fallback
        workflow_id = getattr(context, "workflow_id", None) or f"dsl.{context.route_id}"

        # Формируем payload
        if self._payload_path:
            import jmespath

            payload_data = jmespath.search(self._payload_path, exchange.in_message.body)
        else:
            payload_data = exchange.in_message.body

        payload = {
            "request_id": signal_id,
            "route_id": context.route_id if hasattr(context, "route_id") else None,
            "title": self._title,
            "description": self._description,
            "payload": payload_data,
            "approvers": self._approvers,
            "created_at": time.time(),
            "expires_at": time.time() + self._timeout,
        }

        # Регистрируем pending signal в HitlService
        from src.backend.services.workflows.hitl_service import HitlPendingSignal

        signal = HitlPendingSignal(
            signal_id=signal_id,
            workflow_id=workflow_id,
            tenant_id=str(tenant_id),
            signal_name="hitl_approve",
            initiator=payload_data.get("initiator", "unknown")
            if isinstance(payload_data, dict)
            else "unknown",
            title=self._title,
            payload=payload,
        )

        await self._hitl_service.register_pending(signal)

        # Логируем начало ожидания
        _logger.info(
            "HITL approval registered: signal_id=%s, title=%s, workflow_id=%s",
            signal_id,
            self._title,
            workflow_id,
        )

        # Ожидаем решения с polling
        decision = await self._wait_for_decision(signal_id)

        # Обрабатываем решение
        if decision is None:
            exchange.fail(f"HITL approval timeout: {signal_id}")
            return

        action = decision.resolved_action

        if action == "approve":
            _logger.info("HITL approved: signal_id=%s", signal_id)
            exchange.properties["hitl_approval"] = {
                "signal_id": signal_id,
                "action": "approved",
                "decided_by": decision.resolved_by,
                "decided_at": decision.resolved_at.isoformat()
                if decision.resolved_at
                else None,
            }
            # body уже содержит результат предыдущих шагов

        elif action == "reject":
            _logger.warning(
                "HITL rejected: signal_id=%s, by=%s", signal_id, decision.resolved_by
            )
            exchange.fail(
                f"HITL approval rejected by {decision.resolved_by}: {signal_id}"
            )
            return

        elif action == "request_info":
            _logger.info(
                "HITL requested info: signal_id=%s, by=%s",
                signal_id,
                decision.resolved_by,
            )
            # Выполняем request_info_processors для сбора дополнительных данных
            from src.backend.dsl.engine.processors.base import run_sub_processors

            exchange.properties["hitl_request_info"] = {
                "signal_id": signal_id,
                "requested_by": decision.resolved_by,
            }
            await run_sub_processors(self._request_info_processors, exchange, context)

            # После сбора данных повторно регистрируем signal для продолжения
            signal = HitlPendingSignal(
                signal_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                tenant_id=str(tenant_id),
                signal_name="hitl_approve",
                initiator=payload_data.get("initiator", "unknown")
                if isinstance(payload_data, dict)
                else "unknown",
                title=self._title,
                payload=payload,
            )
            await self._hitl_service.register_pending(signal)

            # Ждём следующего решения
            next_decision = await self._wait_for_decision(signal.signal_id)
            if next_decision is None or next_decision.resolved_action != "approve":
                exchange.fail(
                    f"HITL approval not approved after info request: {signal_id}"
                )
                return

            exchange.properties["hitl_approval"] = {
                "signal_id": signal_id,
                "action": "approved_after_info_request",
                "decided_by": next_decision.resolved_by,
            }

        else:
            exchange.fail(f"Unknown HITL action: {action}")

    async def _wait_for_decision(self, signal_id: str):
        """Poll HitlService с exponential backoff до получения решения."""
        poll_interval = 1.0  # Начальный интервал
        max_poll_interval = 30.0
        timeout_at = time.time() + self._timeout

        while time.time() < timeout_at:
            await asyncio.sleep(min(poll_interval, timeout_at - time.time()))

            signal = await self._hitl_service.get(signal_id)
            if signal is None:
                _logger.warning("HITL signal not found: %s", signal_id)
                return None

            if signal.is_resolved:
                return signal

            # Exponential backoff
            poll_interval = min(poll_interval * 1.2, max_poll_interval)

        # Timeout
        _logger.warning("HITL timeout: signal_id=%s", signal_id)
        return None

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует HITL-approval в YAML-spec.

        Returns:
            YAML-spec процессора или None если не сериализуется
            (например, если используется payload_path с jmespath).
        """
        if self._payload_path is not None:
            # JMESPath expressions are not serializable to YAML
            return None

        spec: dict[str, Any] = {"title": self._title}
        if self._description:
            spec["description"] = self._description
        if self._approvers:
            spec["approvers"] = self._approvers
        if self._timeout != 86_400.0:
            spec["timeout_seconds"] = self._timeout
        if self._request_info_processors:
            # Cannot serialize processors
            return None

        return {"hitl_approval": spec}
