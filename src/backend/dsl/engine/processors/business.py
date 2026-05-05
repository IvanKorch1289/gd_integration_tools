"""Бизнес-процессоры: multi-tenancy, cost tracking, human-in-the-loop, outbox.

Эти процессоры решают типовые задачи банковской шины:

* :class:`TenantScopeProcessor` — проставляет ``tenant_id`` в Exchange для
  последующей фильтрации в репозиториях и очередях.
* :class:`CostTrackerProcessor` — суммирует стоимость pipeline'а
  (LLM-токены × цена, HTTP-вызовы, DB-операции) → Prometheus-метрика.
* :class:`HumanApprovalProcessor` — приостанавливает pipeline, публикует
  запрос на согласование и ожидает ответа (resume через action).
* :class:`OutboxProcessor` — запись события в outbox-таблицу для
  надёжной публикации через background-worker (transactional outbox).
* :class:`DataMaskingProcessor` — маскирует PII/PCI-поля прямо в pipeline
  перед логированием или передачей наружу.
* :class:`ComplianceLabelProcessor` — проставляет метки (PII/FIN/PCI) на
  Exchange для downstream-audit и DLP.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "TenantScopeProcessor",
    "CostTrackerProcessor",
    "HumanApprovalProcessor",
    "OutboxProcessor",
    "DataMaskingProcessor",
    "ComplianceLabelProcessor",
)

logger = logging.getLogger("dsl.business")


# ──────────────────── Multi-tenancy ────────────────────


class TenantScopeProcessor(BaseProcessor):
    """Проставляет ``tenant_id`` в :class:`Exchange` из заголовка или body-field.

    Downstream процессоры (репозитории, очереди) используют ``tenant_id`` для
    row-level фильтрации. По-умолчанию читает из заголовка ``x-tenant-id``.
    """

    def __init__(
        self,
        *,
        header: str = "x-tenant-id",
        body_path: str | None = None,
        required: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "tenant-scope")
        self._header = header
        self._body_path = body_path
        self._required = required

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tenant_id = exchange.in_message.headers.get(self._header)
        if tenant_id is None and self._body_path:
            try:
                import jmespath

                tenant_id = jmespath.search(self._body_path, exchange.in_message.body)
            except Exception:  # noqa: BLE001
                tenant_id = None
        if tenant_id is None:
            if self._required:
                exchange.fail(f"Отсутствует tenant_id (header={self._header!r})")
            return
        exchange.properties["tenant_id"] = str(tenant_id)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._header != "x-tenant-id":
            spec["header"] = self._header
        if self._body_path is not None:
            spec["body_path"] = self._body_path
        if self._required is not True:
            spec["required"] = self._required
        return {"tenant_scope": spec}


# ──────────────────── Cost tracking ────────────────────


class CostTrackerProcessor(BaseProcessor):
    """Учёт стоимости pipeline-инстанса в ``Exchange.properties['cost']``.

    В конце pipeline значение можно выгрузить в Prometheus counter или
    Clickhouse для аналитики. Инициализирует словарь структуры::

        {"llm_tokens_in": 0, "llm_tokens_out": 0, "http_calls": 0,
         "db_ops": 0, "usd": 0.0}

    Downstream-процессоры (LLMCallProcessor, HttpCallProcessor) сами
    инкрементируют соответствующие поля через ``context`` (тут — заготовка).
    """

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "cost-tracker")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.properties.setdefault(
            "cost",
            {
                "llm_tokens_in": 0,
                "llm_tokens_out": 0,
                "http_calls": 0,
                "db_ops": 0,
                "usd": 0.0,
                "started_at": time.time(),
            },
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {"cost_tracker": {}}


# ──────────────────── Human-in-the-loop approval ────────────────────


class HumanApprovalProcessor(BaseProcessor):
    """Останавливает pipeline, публикует запрос approval, ожидает ответа.

    Использует ``approval_store`` (любой storage с ``set`` / ``wait``) для
    хранения статуса запроса. Pipeline может быть возобновлён через action
    ``approvals.approve`` / ``approvals.reject``.

    Args:
        approval_store: Объект с методами ``request(id, payload)``, ``wait(id, timeout)``.
        notifier: Callable для уведомления согласующих (email/Express/etc).
        timeout_seconds: Максимальное ожидание ответа.
        approvers: Список получателей уведомления.
    """

    def __init__(
        self,
        *,
        approval_store: Any,
        notifier: Any = None,
        timeout_seconds: float = 86_400.0,
        approvers: list[str] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "human-approval")
        self._store = approval_store
        self._notifier = notifier
        self._timeout = timeout_seconds
        self._approvers = approvers or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        request_id = str(uuid.uuid4())
        payload = {
            "request_id": request_id,
            "route_id": context.route_id if hasattr(context, "route_id") else None,
            "body": exchange.in_message.body,
            "approvers": self._approvers,
            "expires_at": time.time() + self._timeout,
        }
        await self._store.request(request_id, payload)

        # Нотификация (best-effort, не валит pipeline).
        if self._notifier is not None and self._approvers:
            try:
                result = self._notifier(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Approval notify failed: %s", exc)

        decision = await self._store.wait(request_id, timeout=self._timeout)
        exchange.properties["approval"] = decision
        if not decision or decision.get("status") != "approved":
            exchange.fail(f"Approval отклонён/истёк: {decision}")


# ──────────────────── Outbox (transactional messaging) ────────────────────


class OutboxProcessor(BaseProcessor):
    """Записывает событие в outbox-таблицу для надёжной публикации.

    Паттерн Transactional Outbox: событие сохраняется в той же транзакции,
    что и бизнес-данные; отдельный worker читает таблицу и публикует в
    брокер, обеспечивая at-least-once доставку.

    Args:
        topic: Тема/очередь для публикации. Префикс определяет broker:
            ``kafka:<topic>``, ``rabbit:<queue>``, ``redis:<stream>``.
            Без префикса — kafka по умолчанию.
        outbox_writer: Опциональный callable ``async (topic, payload, headers) -> Any``.
            По умолчанию используется
            :func:`app.infrastructure.repositories.outbox.write`, который
            сохраняет запись в таблицу ``outbox_messages``.
    """

    def __init__(
        self, *, topic: str, outbox_writer: Any = None, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"outbox:{topic}")
        self._topic = topic
        self._writer = outbox_writer

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        payload = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )
        headers = dict(exchange.in_message.headers)

        writer = self._writer
        if writer is None:
            from src.backend.infrastructure.repositories.outbox import (
                write as default_writer,
            )

            writer = default_writer

        try:
            await writer(topic=self._topic, payload=payload, headers=headers)
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"Outbox write failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        if self._writer is not None:
            return None
        return {"outbox": {"topic": self._topic}}


# ──────────────────── Data masking ────────────────────

_DEFAULT_PATTERNS = {
    "inn": re.compile(r"\b\d{10}(?:\d{2})?\b"),
    "snils": re.compile(r"\b\d{3}-\d{3}-\d{3} \d{2}\b"),
    "card": re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    "passport_ru": re.compile(r"\b\d{4} \d{6}\b"),
    "email": re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
    "phone": re.compile(
        r"\b(?:\+?7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b"
    ),
}


class DataMaskingProcessor(BaseProcessor):
    """Маскирует PII/PCI в теле сообщения перед логированием или передачей наружу.

    По-умолчанию маскирует ИНН, СНИЛС, номер карты, паспорт РФ, email, телефон.
    Модифицирует ``in_message.body`` (если строка или JSON) in-place.
    """

    def __init__(
        self,
        *,
        patterns: list[str] | None = None,
        replacement: str = "***",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "mask")
        chosen = patterns or list(_DEFAULT_PATTERNS.keys())
        self._patterns_arg = patterns
        self._patterns = [
            _DEFAULT_PATTERNS[p] for p in chosen if p in _DEFAULT_PATTERNS
        ]
        self._replacement = replacement

    def _mask_str(self, text: str) -> str:
        for pat in self._patterns:
            text = pat.sub(self._replacement, text)
        return text

    def _mask_value(self, value: Any) -> Any:
        # Рекурсивно проходим по JSON-структуре; листовые строки маскируются.
        if isinstance(value, str):
            return self._mask_str(value)
        if isinstance(value, dict):
            return {k: self._mask_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._mask_value(v) for v in value]
        return value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.in_message.body = self._mask_value(exchange.in_message.body)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._patterns_arg is not None:
            spec["patterns"] = list(self._patterns_arg)
        if self._replacement != "***":
            spec["replacement"] = self._replacement
        return {"mask": spec}


# ──────────────────── Compliance labels ────────────────────


class ComplianceLabelProcessor(BaseProcessor):
    """Проставляет метки compliance на Exchange.

    Метки (``PII``, ``PCI``, ``FIN``, ``MED``, ``GDPR``) хранятся в
    ``properties['compliance_labels']`` и используются downstream
    middleware'ами (DLP, audit, masking) для условного поведения.
    """

    def __init__(self, *, labels: list[str], name: str | None = None) -> None:
        super().__init__(name=name or f"labels:{','.join(labels)}")
        self._labels = labels

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        existing = set(exchange.properties.get("compliance_labels", []))
        existing.update(self._labels)
        exchange.properties["compliance_labels"] = sorted(existing)

    def to_spec(self) -> dict[str, Any] | None:
        return {"compliance_labels": {"labels": list(self._labels)}}
