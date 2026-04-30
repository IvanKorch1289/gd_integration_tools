"""Email push-канал для :class:`InvocationResponse` (W22 этап B).

Push-only backend: отправляет письмо с результатом через
:class:`EmailAdapter` (notifications/adapters/email.py), который под
капотом использует SMTP-pool из :mod:`infrastructure.clients.transport.smtp`.

Recipient берётся из ``response.metadata["email"]`` (или
``metadata["recipient_email"]``); если не указан — backend пишет
warning и пропускает доставку. ``fetch`` всегда возвращает ``None`` —
у канала нет сохранённого state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from src.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)
from src.core.interfaces.invoker import InvocationResponse, InvocationStatus

__all__ = ("EmailReplyChannel", "EmailNotifier")

logger = logging.getLogger("messaging.invocation_replies.email")

#: Префикс subject email-писем; конкатенируется с ``invocation_id``.
DEFAULT_SUBJECT_PREFIX = "Invocation result"


@runtime_checkable
class EmailNotifier(Protocol):
    """Минимальный контракт email-отправителя.

    Совместим с :class:`infrastructure.notifications.adapters.email.EmailAdapter`
    (kwargs-based ``send``) — изолирует backend от конкретного adapter'а.
    """

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None: ...


class EmailReplyChannel(InvocationReplyChannel):
    """Доставляет :class:`InvocationResponse` письмом.

    Recipient читается из ``response.metadata`` по ключам ``email`` либо
    ``recipient_email`` (в указанном порядке). Subject формируется из
    ``subject_prefix`` + ``invocation_id``; body — JSON-сериализованный
    response.

    Args:
        notifier: Совместимый с Protocol email-отправитель.
            При ``None`` — lazy-резолв :class:`EmailAdapter` с дефолтным
            ``from_address`` из ``settings.smtp.username`` (если доступен).
        subject_prefix: Текст в начале subject (по умолчанию
            ``Invocation result``).
        default_recipient: Fallback recipient, если ``response.metadata``
            не содержит email-адреса. Полезно для одиночного оператора
            в dev_light; ``None`` — пропускать доставку.
    """

    def __init__(
        self,
        notifier: EmailNotifier | None = None,
        *,
        subject_prefix: str = DEFAULT_SUBJECT_PREFIX,
        default_recipient: str | None = None,
    ) -> None:
        self._notifier = notifier
        self._subject_prefix = subject_prefix
        self._default_recipient = default_recipient

    @property
    def kind(self) -> ReplyChannelKind:
        return ReplyChannelKind.EMAIL

    async def send(self, response: InvocationResponse) -> None:
        recipient = self._resolve_recipient(response)
        if recipient is None:
            logger.warning(
                "EmailReplyChannel: recipient не найден в metadata "
                "(invocation_id=%s); доставка пропущена",
                response.invocation_id,
            )
            return

        notifier = self._notifier or self._lazy_notifier()
        if notifier is None:
            logger.warning(
                "EmailReplyChannel: EmailAdapter недоступен "
                "(invocation_id=%s); доставка пропущена",
                response.invocation_id,
            )
            return

        subject = f"{self._subject_prefix} {response.invocation_id}"
        body = _format_body(response)
        try:
            await notifier.send(
                recipient=recipient,
                subject=subject,
                body=body,
                metadata={"invocation_id": response.invocation_id},
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "EmailReplyChannel.send failed (invocation_id=%s, recipient=%s)",
                response.invocation_id,
                recipient,
            )

    async def fetch(self, invocation_id: str) -> InvocationResponse | None:
        return None

    def _resolve_recipient(self, response: InvocationResponse) -> str | None:
        meta = response.metadata or {}
        recipient = meta.get("email") or meta.get("recipient_email")
        if isinstance(recipient, str) and recipient:
            return recipient
        return self._default_recipient

    def _lazy_notifier(self) -> EmailNotifier | None:
        """Lazy-инициализация EmailAdapter с дефолтным from_address.

        Возвращает ``None``, если SMTP-настройки или адаптер недоступны
        (например, в dev_light без SMTP).
        """
        try:
            from src.core.config.settings import settings
            from src.infrastructure.notifications.adapters.email import EmailAdapter

            from_address = getattr(getattr(settings, "smtp", None), "username", None)
            if not from_address:
                return None
            return EmailAdapter(from_address=str(from_address))
        except Exception:  # noqa: BLE001
            return None


def _format_body(response: InvocationResponse) -> str:
    """Форматирует :class:`InvocationResponse` в plain-text email body."""
    payload = asdict(response)
    payload["status"] = response.status.value
    payload["mode"] = response.mode.value
    if response.status is InvocationStatus.ERROR:
        head = f"Status: ERROR\nError: {response.error or ''}\n\n"
    else:
        head = f"Status: {response.status.value.upper()}\n\n"
    try:
        return head + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except TypeError, ValueError:
        return head + repr(response)
