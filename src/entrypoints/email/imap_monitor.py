"""IMAP-мониторинг входящих email.

Периодически опрашивает IMAP-ящик, парсит новые письма
и передаёт их в DSL-маршрут для обработки.
"""

import asyncio
import email
import imaplib
import logging
from dataclasses import dataclass
from typing import Any

from app.dsl.service import get_dsl_service

__all__ = ("ImapMonitor", "ImapConfig")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImapConfig:
    """Конфигурация IMAP-мониторинга.

    Attrs:
        host: IMAP-сервер.
        port: Порт (993 для IMAPS).
        username: Логин.
        password: Пароль.
        folder: Папка для мониторинга.
        route_id: DSL-маршрут для обработки писем.
        poll_interval: Интервал опроса (сек).
        use_ssl: Использовать SSL.
    """

    host: str
    port: int = 993
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    route_id: str = ""
    poll_interval: float = 60.0
    use_ssl: bool = True


class ImapMonitor:
    """Монитор входящих email через IMAP.

    Подключается к ящику, ищет непрочитанные письма,
    парсит их и отправляет в DSL для обработки.
    """

    def __init__(self, config: ImapConfig) -> None:
        self.config = config
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def _fetch_unseen_sync(self) -> list[dict[str, Any]]:
        """Синхронно получает непрочитанные письма.

        Returns:
            Список словарей с данными писем.
        """
        klass = imaplib.IMAP4_SSL if self.config.use_ssl else imaplib.IMAP4
        conn = klass(self.config.host, self.config.port)

        try:
            conn.login(self.config.username, self.config.password)
            conn.select(self.config.folder)

            _, msg_ids = conn.search(None, "UNSEEN")
            if not msg_ids or not msg_ids[0]:
                return []

            messages: list[dict[str, Any]] = []

            for msg_id in msg_ids[0].split():
                _, data = conn.fetch(msg_id, "(RFC822)")
                if not data or not data[0]:
                    continue

                raw = data[0][1]
                if isinstance(raw, bytes):
                    msg = email.message_from_bytes(raw)
                else:
                    continue

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode(
                                    errors="replace"
                                )
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode(errors="replace")

                messages.append(
                    {
                        "message_id": msg.get("Message-ID", ""),
                        "from": msg.get("From", ""),
                        "to": msg.get("To", ""),
                        "subject": msg.get("Subject", ""),
                        "date": msg.get("Date", ""),
                        "body": body,
                    }
                )

            return messages
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    async def _poll_loop(self) -> None:
        """Цикл опроса IMAP-ящика."""
        while self._running:
            try:
                messages = await asyncio.to_thread(
                    self._fetch_unseen_sync
                )

                for msg_data in messages:
                    logger.info(
                        "Email: from=%s, subject=%s",
                        msg_data.get("from"),
                        msg_data.get("subject"),
                    )

                    try:
                        dsl = get_dsl_service()
                        await dsl.dispatch(
                            route_id=self.config.route_id,
                            body=msg_data,
                            headers={
                                "x-source": "email_imap",
                                "x-email-from": msg_data.get(
                                    "from", ""
                                ),
                            },
                        )
                    except Exception:
                        logger.exception(
                            "Ошибка обработки email: %s",
                            msg_data.get("subject"),
                        )

            except Exception:
                logger.exception("IMAP poll ошибка")

            await asyncio.sleep(self.config.poll_interval)

    async def start(self) -> None:
        """Запускает мониторинг."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "IMAP мониторинг запущен: %s@%s",
            self.config.username,
            self.config.host,
        )

    async def stop(self) -> None:
        """Останавливает мониторинг."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
