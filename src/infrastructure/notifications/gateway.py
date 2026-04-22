"""NotificationGateway — единый фасад для отправки уведомлений (IL2.2, ADR-023).

Композитор:
  * `TemplateRegistry` — рендеринг subject+body из шаблона с локализацией.
  * `PriorityRouter` — queueing per priority (tx / marketing).
  * `adapters` — конкретный transport (email / sms / slack / teams / ...).
  * `DLQ` — неуспешные сообщения после N retry.

API:

    gateway = get_gateway()
    result = await gateway.send(
        channel="email",
        template_key="kyc_approved",
        locale="ru",
        context={"name": "Иван"},
        recipient="ivan@example.com",
        priority="tx",
    )
    # result.status ∈ {"queued", "sent", "failed", "dlq"}

Sugar: `send_tx(...)` / `send_marketing(...)` эквивалентны `send(priority=...)`.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.infrastructure.notifications.priority import (
    Priority,
    PriorityRouter,
    NotificationBacklogError,
)
from app.infrastructure.notifications.templates import (
    TemplateRegistry,
    get_template_registry,
)


_logger = logging.getLogger(__name__)


ChannelKind = Literal[
    "email", "sms", "slack", "teams", "telegram", "webhook", "express"
]


@dataclass(slots=True)
class SendRequest:
    """Заявка на отправку (после template rendering + routing)."""

    request_id: str
    channel: ChannelKind
    recipient: str
    subject: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)
    priority: Priority = "tx"
    idempotency_key: str | None = None
    template_key: str | None = None
    locale: str | None = None


@dataclass(slots=True)
class SendResult:
    """Результат вызова gateway.send()."""

    request_id: str
    status: Literal["queued", "sent", "failed", "dlq"]
    error: str | None = None
    duration_ms: float = 0.0


class UnknownChannelError(KeyError):
    """Канал с таким именем не зарегистрирован."""


class NotificationGateway:
    """Единый фасад для всех уведомлений.

    Не singleton в конструкторе — `get_gateway()` возвращает managed instance
    через `ConnectorRegistry` (через `InfrastructureClient` lifecycle).
    Здесь держим простой lazy singleton для удобства работы.
    """

    _instance: "NotificationGateway | None" = None

    def __init__(
        self,
        *,
        template_registry: TemplateRegistry | None = None,
        router: PriorityRouter | None = None,
        max_retries: int = 3,
    ) -> None:
        self._templates = template_registry or get_template_registry()
        self._router = router or PriorityRouter()
        self._channels: dict[str, Any] = {}  # kind → NotificationChannel-adapter
        self._max_retries = max_retries
        self._started = False

    @classmethod
    def instance(cls) -> "NotificationGateway":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # -- Lifecycle ----------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        await self._router.start()
        self._started = True
        _logger.info(
            "notification gateway started",
            extra={"channels": list(self._channels.keys())},
        )

    async def stop(self) -> None:
        if not self._started:
            return
        await self._router.stop()
        self._started = False
        _logger.info("notification gateway stopped")

    # -- Регистрация каналов -----------------------------------------

    def register_channel(self, channel: Any) -> None:
        """Зарегистрировать channel-адаптер.

        `channel.kind` — string identifier. Адаптер реализует Protocol
        `NotificationChannel` (см. `adapters/base.py`).
        """
        kind = getattr(channel, "kind", None)
        if not kind:
            raise ValueError("Channel adapter must expose `.kind` attribute")
        self._channels[kind] = channel
        _logger.debug("channel adapter registered", extra={"kind": kind})

    def channel_kinds(self) -> list[str]:
        return sorted(self._channels.keys())

    # -- Send API -----------------------------------------------------

    async def send(
        self,
        *,
        channel: ChannelKind,
        template_key: str,
        locale: str = "ru",
        context: dict[str, Any] | None = None,
        recipient: str,
        priority: Priority = "tx",
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        """Главная точка входа.

        Шаги:
          1. Render template (`TemplateRegistry.render`).
          2. Создать `SendRequest` с request_id (uuid4) и idempotency_key.
          3. Поставить в `PriorityRouter` с адаптером конкретного канала.
          4. Вернуть `SendResult(status="queued", ...)`.

        `status="sent"` возвращается только при `wait=True` (будущая опция),
        сейчас — всегда "queued" или немедленная ошибка template rendering.
        """
        start = time.perf_counter()
        request_id = str(uuid.uuid4())

        # 1. Template rendering.
        try:
            rendered = self._templates.render(
                key=template_key,
                locale=locale,
                context=context,
                channel_kind=channel,
            )
        except Exception as exc:  # noqa: BLE001
            return SendResult(
                request_id=request_id,
                status="failed",
                error=f"template: {type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )

        # 2. Проверить канал.
        adapter = self._channels.get(channel)
        if adapter is None:
            return SendResult(
                request_id=request_id,
                status="failed",
                error=f"channel '{channel}' not registered",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )

        req = SendRequest(
            request_id=request_id,
            channel=channel,
            recipient=recipient,
            subject=rendered.subject,
            body=rendered.body,
            metadata=metadata or {},
            priority=priority,
            idempotency_key=idempotency_key,
            template_key=template_key,
            locale=locale,
        )

        # 3. Enqueue.
        try:
            await self._router.submit(
                priority=priority,
                payload=req,
                callback=self._make_delivery_callback(adapter),
            )
        except NotificationBacklogError as exc:
            # Переполнение — немедленно в DLQ (логически; сейчас просто fail).
            return SendResult(
                request_id=request_id,
                status="dlq",
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )

        return SendResult(
            request_id=request_id,
            status="queued",
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )

    async def send_tx(self, **kwargs: Any) -> SendResult:
        """Sugar для priority='tx'."""
        kwargs.pop("priority", None)
        return await self.send(priority="tx", **kwargs)

    async def send_marketing(self, **kwargs: Any) -> SendResult:
        """Sugar для priority='marketing'."""
        kwargs.pop("priority", None)
        return await self.send(priority="marketing", **kwargs)

    # -- Internal -----------------------------------------------------

    def _make_delivery_callback(self, adapter: Any) -> Any:
        """Закрытие со ссылкой на adapter и max_retries.

        При ошибках после `max_retries` сообщение уйдёт в DLQ (в следующей
        версии — сейчас только логируется). DLQ-таблица и replayer — в
        следующем micro-commit этого чанка.
        """
        max_retries = self._max_retries

        async def _deliver(req: SendRequest) -> None:
            attempt = 0
            last_error: str | None = None
            while attempt < max_retries:
                attempt += 1
                try:
                    await adapter.send(
                        recipient=req.recipient,
                        subject=req.subject,
                        body=req.body,
                        metadata={
                            "request_id": req.request_id,
                            "priority": req.priority,
                            "idempotency_key": req.idempotency_key,
                            **req.metadata,
                        },
                    )
                    _logger.info(
                        "notification sent",
                        extra={
                            "request_id": req.request_id,
                            "channel": req.channel,
                            "priority": req.priority,
                            "attempts": attempt,
                        },
                    )
                    return
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{type(exc).__name__}: {exc}"
                    _logger.warning(
                        "notification attempt failed",
                        extra={
                            "request_id": req.request_id,
                            "attempt": attempt,
                            "max_retries": max_retries,
                            "error": last_error,
                        },
                    )
            _logger.error(
                "notification exhausted retries — moving to DLQ",
                extra={
                    "request_id": req.request_id,
                    "channel": req.channel,
                    "template_key": req.template_key,
                    "last_error": last_error,
                },
            )
            # В следующем micro-commit — insert в notification_dlq таблицу.
            # Пока: emit event для out-of-band обработки (напр., outbox publisher).

        return _deliver


def get_gateway() -> NotificationGateway:
    """Глобальный helper для бизнес-кода."""
    return NotificationGateway.instance()


__all__ = (
    "NotificationGateway",
    "SendRequest",
    "SendResult",
    "UnknownChannelError",
    "get_gateway",
)
