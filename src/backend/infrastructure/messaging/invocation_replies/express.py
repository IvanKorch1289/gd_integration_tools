"""Express push-канал для :class:`InvocationResponse` (W22 этап B).

Push-only backend: отправляет в Express Bot диалог сообщение с
результатом через :class:`ExpressAdapter` (notifications/adapters/express.py).

Recipient ``group_chat_id`` берётся из ``response.metadata["express_chat_id"]``
(или ``metadata["group_chat_id"]``). Опционально ``metadata["bot"]``
переопределяет имя бота — используется тот же контракт, что у
:class:`infrastructure.notifications.adapters.express.ExpressAdapter`.

``fetch`` всегда возвращает ``None`` — push-only канал.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from src.backend.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)
from src.backend.core.interfaces.invoker import InvocationResponse, InvocationStatus

__all__ = ("ExpressReplyChannel", "ExpressNotifier")

logger = logging.getLogger("messaging.invocation_replies.express")


@runtime_checkable
class ExpressNotifier(Protocol):
    """Минимальный контракт Express-отправителя.

    Совместим с :class:`infrastructure.notifications.adapters.express.ExpressAdapter`.
    """

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None: ...


class ExpressReplyChannel(InvocationReplyChannel):
    """Доставляет :class:`InvocationResponse` в Express чат.

    Args:
        notifier: Совместимый с Protocol Express-отправитель. При ``None`` —
            lazy-резолв :class:`ExpressAdapter` с дефолтным ``main_bot``.
        default_chat_id: Fallback ``group_chat_id``, если ``metadata`` не
            содержит chat_id (полезно для одиночного канала уведомлений
            оператора).
        default_bot: Имя бота по умолчанию (передаётся в
            :class:`ExpressAdapter`).
    """

    def __init__(
        self,
        notifier: ExpressNotifier | None = None,
        *,
        default_chat_id: str | None = None,
        default_bot: str = "main_bot",
    ) -> None:
        self._notifier = notifier
        self._default_chat_id = default_chat_id
        self._default_bot = default_bot

    @property
    def kind(self) -> ReplyChannelKind:
        return ReplyChannelKind.EXPRESS

    async def send(self, response: InvocationResponse) -> None:
        recipient = self._resolve_recipient(response)
        if recipient is None:
            logger.warning(
                "ExpressReplyChannel: chat_id не найден в metadata "
                "(invocation_id=%s); доставка пропущена",
                response.invocation_id,
            )
            return

        notifier = self._notifier or self._lazy_notifier()
        if notifier is None:
            logger.warning(
                "ExpressReplyChannel: ExpressAdapter недоступен "
                "(invocation_id=%s); доставка пропущена",
                response.invocation_id,
            )
            return

        subject = f"Invocation {response.invocation_id}"
        body = _format_body(response)
        bot = str((response.metadata or {}).get("bot") or self._default_bot)
        try:
            await notifier.send(
                recipient=recipient,
                subject=subject,
                body=body,
                metadata={
                    "bot": bot,
                    "status": (
                        "error" if response.status is InvocationStatus.ERROR else "ok"
                    ),
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "ExpressReplyChannel.send failed (invocation_id=%s, chat_id=%s)",
                response.invocation_id,
                recipient,
            )

    async def fetch(self, invocation_id: str) -> InvocationResponse | None:
        return None

    def _resolve_recipient(self, response: InvocationResponse) -> str | None:
        meta = response.metadata or {}
        chat_id = meta.get("express_chat_id") or meta.get("group_chat_id")
        if isinstance(chat_id, str) and chat_id:
            return chat_id
        return self._default_chat_id

    def _lazy_notifier(self) -> ExpressNotifier | None:
        """Lazy-резолв :class:`ExpressAdapter`; ``None`` если Express отключён."""
        try:
            from src.backend.infrastructure.notifications.adapters.express import (
                ExpressAdapter,
            )

            return ExpressAdapter(default_bot=self._default_bot)
        except Exception:  # noqa: BLE001
            return None


def _format_body(response: InvocationResponse) -> str:
    """Форматирует :class:`InvocationResponse` в Markdown-текст для Express."""
    if response.status is InvocationStatus.ERROR:
        return f"❌ Error: {response.error or 'unknown'}"
    payload = asdict(response)
    payload["status"] = response.status.value
    payload["mode"] = response.mode.value
    try:
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        body = repr(response)
    return f"```\n{body}\n```"
