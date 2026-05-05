"""R2.3 — `NotifyCascadeProcessor`: cross-cutting fire-and-forget policy.

DSL-процессор для отправки уведомлений по цепочке fallback-каналов:

* Берёт список ``NotificationAdapter`` (Slack / Email / Telegram / ...).
* В фоновом task'е пытается отправить через первый; при
  ``ConnectionError`` / fail — переходит к следующему.
* Не блокирует основной pipeline (fire-and-forget); ошибки идут в логи.
* На каждом канале — встроенный retry (tenacity) с экспоненциальным
  backoff'ом до перехода к fallback'у.

Использование (Python builder)::

    builder.notify_cascade(
        recipient_path="properties.user_email",
        subject="Order shipped",
        body_path="body",
        adapters=[slack_adapter, email_adapter, telegram_adapter],
    )

Использование (YAML — через `notify_cascade` метод RouteBuilder)::

    processors:
      - notify_cascade:
          recipient_path: properties.user_email
          subject: "Order shipped"
          body_path: body
          # adapters резолвятся из DI registry по имени
          adapter_names: ["slack", "email", "telegram"]
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from src.backend.core.interfaces.notification import (
    NotificationAdapter,
    NotificationMessage,
)
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("NotifyCascadeProcessor",)


_logger = logging.getLogger("dsl.notify_cascade")


class NotifyCascadeProcessor(BaseProcessor):
    """Fire-and-forget cascade-уведомлений с fallback-цепочкой каналов."""

    def __init__(
        self,
        *,
        adapters: Sequence[NotificationAdapter],
        recipient_path: str = "properties.recipient",
        subject: str = "",
        body_path: str = "body",
        retries_per_adapter: int = 2,
        retry_delay_s: float = 0.5,
        name: str | None = None,
    ) -> None:
        """Параметры:

        :param adapters: упорядоченный список adapter'ов; пробуются по
            порядку до первого успешного.
        :param recipient_path: ``"properties.<key>"`` /
            ``"headers.<key>"`` / ``"body.<key>"`` — путь к recipient.
        :param subject: тема (статическая; для динамики — pre-step).
        :param body_path: ``"body"`` (по умолчанию — body как str/dict)
            или ``"properties.<key>"`` / ``"headers.<key>"``.
        :param retries_per_adapter: сколько раз пробовать каждый
            adapter ДО перехода к следующему.
        :param retry_delay_s: пауза между retry на одном adapter'е
            (linear, не exponential — по умолчанию 0.5 сек).
        """
        if not adapters:
            raise ValueError("NotifyCascadeProcessor: adapters list cannot be empty")
        super().__init__(name=name or f"notify_cascade({len(adapters)})")
        self._adapters = tuple(adapters)
        self._recipient_path = recipient_path
        self._subject = subject
        self._body_path = body_path
        self._retries = retries_per_adapter
        self._retry_delay = retry_delay_s

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Запустить fire-and-forget cascade-task; вернуться мгновенно."""
        recipient = self._extract_path(exchange, self._recipient_path)
        body = self._extract_path(exchange, self._body_path)
        message = NotificationMessage(
            recipient=str(recipient) if recipient is not None else "",
            subject=self._subject,
            body=str(body) if body is not None else "",
        )

        task = asyncio.create_task(
            self._cascade_send(message),
            name=f"notify_cascade:{self._adapters[0].channel}",
        )
        task.add_done_callback(_swallow_exc)
        exchange.properties.setdefault("notify_cascade_tasks", []).append(
            f"notify_cascade:{id(task)}"
        )

    async def _cascade_send(self, message: NotificationMessage) -> None:
        """Перебор adapter'ов с retry до первого успешного."""
        last_exc: Exception | None = None
        for adapter in self._adapters:
            for attempt in range(1, self._retries + 1):
                try:
                    if not await adapter.is_available():
                        _logger.debug(
                            "notify_cascade: %s unavailable, skip", adapter.channel
                        )
                        break
                    track_id = await adapter.send(message)
                    _logger.info(
                        "notify_cascade delivered via %s: track_id=%s",
                        adapter.channel,
                        track_id,
                    )
                    return
                except ConnectionError as exc:
                    last_exc = exc
                    _logger.warning(
                        "notify_cascade %s attempt %d/%d failed: %s",
                        adapter.channel,
                        attempt,
                        self._retries,
                        exc,
                    )
                    if attempt < self._retries:
                        await asyncio.sleep(self._retry_delay)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    _logger.warning(
                        "notify_cascade %s unexpected exc: %s", adapter.channel, exc
                    )
                    break  # не retry на не-ConnectionError'ах
        _logger.error(
            "notify_cascade: all %d adapters failed; last_exc=%s",
            len(self._adapters),
            last_exc,
        )

    def _extract_path(self, exchange: Exchange[Any], path: str) -> Any:
        """Извлечь значение по ``body|properties.<k>|headers.<k>``."""
        if path == "body":
            return exchange.in_message.body
        if path.startswith("body."):
            key = path.removeprefix("body.")
            body = exchange.in_message.body
            return body.get(key) if isinstance(body, dict) else None
        if path.startswith("properties."):
            return exchange.properties.get(path.removeprefix("properties."))
        if path.startswith("headers."):
            return exchange.in_message.headers.get(path.removeprefix("headers."))
        raise ValueError(f"NotifyCascadeProcessor: unsupported path={path!r}")


def _swallow_exc(task: asyncio.Task[None]) -> None:
    """Done-callback: гасит unhandled exception у background task."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.debug("notify_cascade task exception: %s", exc)
