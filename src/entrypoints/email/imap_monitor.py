"""IMAP-мониторинг входящих email.

Async-реализация на ``aioimaplib`` (A2 / ADR-004). Синхронный ``imaplib``
удалён: блокирующий I/O в ``asyncio.to_thread`` под капотом был серьёзным
узким местом и маскировал ошибки TLS.

Пароль берётся из Vault (см. ``app.core.config.vault_refresher``), если
указан ``ImapConfig.password_vault_ref`` — иначе используется явный
``password`` (только для dev).
"""

from __future__ import annotations

import asyncio
import email
import logging
import ssl
from dataclasses import dataclass
from email.message import Message
from typing import Any

from app.dsl.service import get_dsl_service

__all__ = ("ImapMonitor", "ImapConfig")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImapConfig:
    """Конфигурация IMAP-мониторинга.

    Attrs:
        host: IMAP-сервер.
        port: Порт (993 для IMAPS, 143 для STARTTLS).
        username: Логин.
        password: Пароль (для dev). В prod используйте ``password_vault_ref``.
        password_vault_ref: Ссылка вида ``vault:<path>#<key>`` (см. VaultSecretRefresher).
        folder: Папка для мониторинга.
        route_id: DSL-маршрут для обработки писем.
        poll_interval: Интервал опроса (сек).
        use_ssl: Использовать SSL (IMAPS, порт 993). Иначе STARTTLS на 143.
        starttls: Применить STARTTLS для plain IMAP (если use_ssl=False).
        verify_cert: Проверять серверный сертификат.
    """

    host: str
    port: int = 993
    username: str = ""
    password: str = ""
    password_vault_ref: str = ""
    folder: str = "INBOX"
    route_id: str = ""
    poll_interval: float = 60.0
    use_ssl: bool = True
    starttls: bool = True
    verify_cert: bool = True


class ImapMonitor:
    """Монитор входящих email через aioimaplib (async)."""

    def __init__(self, config: ImapConfig) -> None:
        self.config = config
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def _resolve_password(self) -> str:
        """Возвращает пароль — из Vault (если указана ref) либо из config."""
        ref = self.config.password_vault_ref
        if ref:
            try:
                from app.core.config.vault_refresher import VaultSecretRefresher

                return await VaultSecretRefresher.get().resolve(ref)
            except Exception as exc:
                logger.error("IMAP Vault-resolve fail (%s): %s — fallback to config.password", ref, exc)
        return self.config.password

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not (self.config.use_ssl or self.config.starttls):
            return None
        ctx = ssl.create_default_context()
        if not self.config.verify_cert:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _fetch_unseen(self) -> list[dict[str, Any]]:
        """Асинхронно получает непрочитанные письма."""
        try:
            from aioimaplib import IMAP4, IMAP4_SSL
        except ImportError:
            logger.warning("aioimaplib не установлен — IMAP отключён")
            return []

        password = await self._resolve_password()
        ssl_ctx = self._ssl_context()

        if self.config.use_ssl:
            client = IMAP4_SSL(host=self.config.host, port=self.config.port, ssl_context=ssl_ctx)
        else:
            client = IMAP4(host=self.config.host, port=self.config.port)

        try:
            await client.wait_hello_from_server()
            if (not self.config.use_ssl) and self.config.starttls:
                await client.starttls(ssl_context=ssl_ctx)
            await client.login(self.config.username, password)
            await client.select(self.config.folder)

            response = await client.search("UNSEEN")
            lines = response.lines or []
            raw_ids = lines[0].decode().split() if lines and lines[0] else []

            messages: list[dict[str, Any]] = []
            for msg_id in raw_ids:
                fetch_resp = await client.fetch(msg_id, "(RFC822)")
                raw_bytes = b""
                for line in fetch_resp.lines or []:
                    if isinstance(line, (bytes, bytearray)) and len(line) > 100:
                        raw_bytes = bytes(line)
                        break
                if not raw_bytes:
                    continue
                messages.append(_parse_email(raw_bytes))
            return messages
        finally:
            try:
                await client.logout()
            except Exception:
                pass

    async def _poll_loop(self) -> None:
        """Цикл опроса IMAP-ящика."""
        while self._running:
            try:
                messages = await self._fetch_unseen()
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
                                "x-email-from": msg_data.get("from", ""),
                            },
                        )
                    except Exception:
                        logger.exception(
                            "Ошибка обработки email: %s", msg_data.get("subject")
                        )
            except Exception:
                logger.exception("IMAP poll ошибка")

            await asyncio.sleep(self.config.poll_interval)

    async def start(self) -> None:
        """Запускает мониторинг."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "IMAP мониторинг запущен: %s@%s (ssl=%s, starttls=%s)",
            self.config.username,
            self.config.host,
            self.config.use_ssl,
            self.config.starttls,
        )

    async def stop(self) -> None:
        """Останавливает мониторинг."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None


def _parse_email(raw: bytes) -> dict[str, Any]:
    """Парсит RFC822 в плоский dict."""
    msg: Message = email.message_from_bytes(raw)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="replace")

    return {
        "message_id": msg.get("Message-ID", ""),
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "body": body,
    }
