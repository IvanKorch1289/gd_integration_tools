"""IMAP-мониторинг входящих email.

Async-реализация на ``aioimaplib`` (A2 / ADR-004). Синхронный ``imaplib``
удалён: блокирующий I/O в ``asyncio.to_thread`` под капотом был серьёзным
узким местом и маскировал ошибки TLS.

Пароль берётся из Vault (см. ``app.core.config.vault_refresher``), если
указан ``ImapConfig.password_vault_ref`` — иначе используется явный
``password`` (только для dev).
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio
import email

import re
import ssl
from dataclasses import dataclass
from email.message import Message
from typing import Any

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.dsl.service import get_dsl_service

__all__ = ("ImapConfig", "ImapMonitor")

logger = get_logger(__name__)


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
        idle_mode: Использовать IMAP IDLE (RFC 2177) вместо polling
            (по умолчанию ``False`` — обратная совместимость).
        idle_timeout: Таймаут одной IDLE-сессии в секундах
            (RFC 2177 рекомендует ≤ 29 минут).
        subject_pattern: Substring или ``re:<regex>`` для темы письма.
            ``None`` — без фильтра.
        from_filter: Substring для From-заголовка. ``None`` — без фильтра.
        since_uid: Не повторно обрабатывать письма с UID ≤ этого значения.
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
    idle_mode: bool = False
    idle_timeout: float = 29 * 60
    subject_pattern: str | None = None
    from_filter: str | None = None
    since_uid: int = 0


class ImapMonitor:
    """Монитор входящих email через aioimaplib (async).

    Sprint 3: добавлены ``idle_mode`` (IMAP IDLE RFC 2177) и фильтры
    по теме / отправителю. По умолчанию используется polling — это
    сохраняет обратную совместимость.
    """

    def __init__(self, config: ImapConfig) -> None:
        self.config = config
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._subject_re = self._compile_subject_pattern(config.subject_pattern)
        self._last_uid: int = config.since_uid

    @staticmethod
    def _compile_subject_pattern(pattern: str | None) -> re.Pattern[str] | None:
        """Превращает ``subject_pattern`` в regex (literal substring или ``re:``)."""
        if not pattern:
            return None
        if pattern.startswith("re:"):
            return re.compile(pattern[3:], flags=re.IGNORECASE)
        return re.compile(re.escape(pattern), flags=re.IGNORECASE)

    def _matches_filters(self, message: dict[str, Any]) -> bool:
        """Применяет фильтры subject/from к распарсенному письму."""
        subject = str(message.get("subject", ""))
        sender = str(message.get("from", ""))
        if self._subject_re is not None and not self._subject_re.search(subject):
            return False
        if (
            self.config.from_filter
            and self.config.from_filter.lower() not in sender.lower()
        ):
            return False
        return True

    async def _resolve_password(self) -> str:
        """Возвращает пароль — из Vault (если указана ref) либо из config."""
        ref = self.config.password_vault_ref
        if ref:
            try:
                from src.backend.core.di.providers import get_vault_refresher_provider

                refresher = get_vault_refresher_provider()
                return await refresher.resolve(ref)
            except Exception as exc:
                logger.error(
                    "IMAP Vault-resolve fail (%s): %s — fallback to config.password",
                    ref,
                    exc,
                )
        return self.config.password

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not (self.config.use_ssl or self.config.starttls):
            return None
        ctx = ssl.create_default_context()
        if not self.config.verify_cert:
            logger.warning(
                "IMAP monitor: verify_cert=False игнорируется (V1 policy: "
                "ssl.CERT_NONE / check_hostname=False запрещены). "
                "Используйте кастомный CA через secrets capability."
            )
        return ctx

    async def _connect(self) -> Any:
        """Подключается к IMAP, делает login + select папки.

        Returns:
            Готовый IMAP-клиент. Вызывающий обязан вызвать ``logout()``.
        """
        from aioimaplib import IMAP4, IMAP4_SSL

        password = await self._resolve_password()
        ssl_ctx = self._ssl_context()

        if self.config.use_ssl:
            client = IMAP4_SSL(
                host=self.config.host, port=self.config.port, ssl_context=ssl_ctx
            )
        else:
            client = IMAP4(host=self.config.host, port=self.config.port)

        await client.wait_hello_from_server()
        if (not self.config.use_ssl) and self.config.starttls:
            await client.starttls(ssl_context=ssl_ctx)
        await client.login(self.config.username, password)
        await client.select(self.config.folder)
        return client

    async def _fetch_unseen(self) -> list[dict[str, Any]]:
        """Асинхронно получает непрочитанные письма (legacy polling путь)."""
        try:
            from aioimaplib import IMAP4, IMAP4_SSL  # noqa: F401
        except ImportError:
            logger.warning("aioimaplib не установлен — IMAP отключён")
            return []

        client = await self._connect()
        try:
            return await self._fetch_messages(client)
        finally:
            try:
                await client.logout()
            except Exception as _:
                logger.debug("IMAP logout failed", exc_info=True)

    async def _fetch_messages(self, client: Any) -> list[dict[str, Any]]:
        """Извлекает UNSEEN-письма с уже подключённого клиента.

        Применяет ``since_uid`` отсечку (UID ≤ ``_last_uid`` пропускаем),
        парсит каждое сообщение и обновляет ``_last_uid`` после успеха.
        """
        try:
            response = await client.search("UNSEEN")
        except Exception as exc:
            logger.warning("IMAP search failed: %s", exc)
            return []

        lines = response.lines or []
        raw_ids = lines[0].decode().split() if lines and lines[0] else []

        messages: list[dict[str, Any]] = []
        for msg_id in raw_ids:
            try:
                uid = int(msg_id)
            except ValueError:
                uid = 0
            if uid and uid <= self._last_uid:
                continue
            try:
                fetch_resp = await client.fetch(msg_id, "(RFC822)")
            except Exception as exc:
                logger.warning("IMAP fetch %s failed: %s", msg_id, exc)
                continue
            raw_bytes = b""
            for line in fetch_resp.lines or []:
                if isinstance(line, (bytes, bytearray)) and len(line) > 100:
                    raw_bytes = bytes(line)
                    break
            if not raw_bytes:
                continue
            parsed = _parse_email(raw_bytes)
            parsed["_uid"] = msg_id
            messages.append(parsed)
            if uid:
                self._last_uid = max(self._last_uid, uid)
        return messages

    async def _dispatch_message(self, msg_data: dict[str, Any]) -> None:
        """Отправляет письмо в DSL-route, если оно прошло фильтры."""
        if not self._matches_filters(msg_data):
            logger.debug(
                "IMAP: письмо отфильтровано (subject=%r, from=%r)",
                msg_data.get("subject"),
                msg_data.get("from"),
            )
            return

        logger.info(
            "Email: from=%s, subject=%s", msg_data.get("from"), msg_data.get("subject")
        )
        try:
            dsl = get_dsl_service()
            await dsl.dispatch(
                route_id=self.config.route_id,
                body=msg_data,
                headers={
                    "x-source": "email_imap",
                    "x-email-from": msg_data.get("from", ""),
                    "x-email-subject": msg_data.get("subject", ""),
                },
            )
        except Exception as _:
            logger.exception("Ошибка обработки email: %s", msg_data.get("subject"))

    async def _poll_loop(self) -> None:
        """Цикл опроса IMAP-ящика (polling, fallback)."""
        while self._running:
            try:
                messages = await self._fetch_unseen()
                for msg_data in messages:
                    await self._dispatch_message(msg_data)
            except Exception as _:
                logger.exception("IMAP poll ошибка")

            await asyncio.sleep(self.config.poll_interval)

    async def _idle_loop(self) -> None:
        """Цикл IMAP IDLE — push-уведомления о новых письмах."""
        try:
            from aioimaplib import IMAP4, IMAP4_SSL  # noqa: F401
        except ImportError:
            logger.warning("aioimaplib не установлен — IMAP отключён")
            return

        while self._running:
            try:
                client = await self._connect()
            except Exception as exc:
                logger.error(
                    "IMAP connect failed: %s — retry in %.1fs",
                    exc,
                    self.config.poll_interval,
                )
                await asyncio.sleep(self.config.poll_interval)
                continue

            try:
                # Первичный fetch — забираем существующие UNSEEN.
                for msg_data in await self._fetch_messages(client):
                    await self._dispatch_message(msg_data)

                while self._running:
                    try:
                        await client.idle_start(timeout=self.config.idle_timeout)
                        await client.wait_server_push()
                    except Exception as exc:
                        logger.warning("IMAP IDLE error: %s — reconnecting", exc)
                        break
                    finally:
                        try:
                            client.idle_done()
                        except Exception as _:
                            logger.debug("IMAP idle_done failed", exc_info=True)
                    for msg_data in await self._fetch_messages(client):
                        await self._dispatch_message(msg_data)
            finally:
                try:
                    await client.logout()
                except Exception as _:
                    logger.debug("IMAP logout failed", exc_info=True)

    async def start(self) -> None:
        """Запускает мониторинг (IDLE или polling — по конфигу)."""
        self._running = True
        coro = self._idle_loop() if self.config.idle_mode else self._poll_loop()
        self._task = get_task_registry().create_task(
            coro, name=f"imap-monitor:{self.config.username}@{self.config.host}"
        )
        logger.info(
            "IMAP мониторинг запущен: %s@%s (ssl=%s, starttls=%s, idle=%s)",
            self.config.username,
            self.config.host,
            self.config.use_ssl,
            self.config.starttls,
            self.config.idle_mode,
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
