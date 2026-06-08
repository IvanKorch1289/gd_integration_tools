"""K3 Sprint-3 Wave 5 — :class:`EmailIMAPSource` + :class:`EmailMessage`.

Предоставляет потоковый итератор писем через IMAP IDLE (aioimaplib).
Отличие от :class:`~infrastructure.sources.email.EmailSource`:

* API — ``async def stream() -> AsyncIterator[EmailMessage]`` вместо
  callback-based ``start(on_event)``.
* Типизированный :class:`EmailMessage` dataclass вместо ``dict``.
* Lazy-import ``aioimaplib`` — модуль загружается только при первом вызове
  :meth:`stream`, что сохраняет быстрый старт (dev_light).
* Используется как источник для ``RouteBuilder.from_imap(...)`` (DSL).

Пример использования::

    async for msg in EmailIMAPSource(host="imap.mail.ru", ...).stream():
        print(msg.subject, msg.from_addr)

Безопасность:
    ssl.create_default_context() + CERT_REQUIRED — обязательно.
    Запрещено ssl.CERT_NONE / check_hostname=False (V1).
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("EmailIMAPSource", "EmailMessage")

if TYPE_CHECKING:
    pass

logger = get_logger("infrastructure.sources.email_imap")


@dataclass(slots=True)
class EmailMessage:
    """Типизированное представление входящего IMAP-письма.

    Args:
        uid: Уникальный идентификатор письма на сервере (IMAP UID).
        subject: Тема письма.
        from_addr: Адрес отправителя.
        to_addr: Адрес получателя.
        body: Текстовое тело письма (plain/html, приоритет plain).
        received_at: Время приёма на клиенте (UTC).
        headers: Словарь всех заголовков письма.
    """

    uid: str
    subject: str
    from_addr: str
    to_addr: str
    body: str
    received_at: datetime
    headers: dict[str, str] = field(default_factory=dict)


def _parse_raw_email(raw: bytes) -> dict[str, str]:
    """Разбирает сырые байты RFC822 в словарь заголовков + тела.

    Args:
        raw: Сырое письмо в формате RFC822.

    Returns:
        Словарь с ключами subject, from, to, body и всеми заголовками.
    """
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    headers: dict[str, str] = {k.lower(): str(v) for k, v in msg.items()}

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in disp:
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception as _:
                    body = ""
                break
    else:
        try:
            raw_payload = msg.get_payload(decode=True)
            if isinstance(raw_payload, bytes):
                body = raw_payload.decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                )
        except Exception as _:
            body = ""

    return {
        **headers,
        "subject": str(msg.get("Subject", "")),
        "from": str(msg.get("From", "")),
        "to": str(msg.get("To", "")),
        "body": body,
    }


class EmailIMAPSource:
    """IMAP-источник писем с API :meth:`stream` (AsyncIterator).

    Реализует IMAP IDLE через ``aioimaplib.IMAP4_SSL``. При потере
    соединения выполняет переподключение с экспоненциальной паузой.

    Args:
        host: IMAP-хост (e.g. ``"imap.gmail.com"``).
        port: IMAP-порт (default 993 — IMAPS).
        user: Логин пользователя.
        password: Пароль (dev-only; в prod передавать через Vault ref).
        folder: IMAP-папка для мониторинга (default ``"INBOX"``).
        subject_filter: Substring-фильтр по теме (case-insensitive). ``None`` — без фильтра.
        from_filter: Substring-фильтр по отправителю (case-insensitive). ``None`` — без фильтра.
        use_ssl: Использовать IMAPS (default True).
        idle_timeout: Таймаут одной IDLE-сессии в секундах (RFC 2177 ≤ 29 мин).
        reconnect_delay: Пауза между попытками переподключения (секунды).
    """

    def __init__(
        self,
        host: str,
        *,
        port: int = 993,
        user: str,
        password: str,
        folder: str = "INBOX",
        subject_filter: str | None = None,
        from_filter: str | None = None,
        use_ssl: bool = True,
        idle_timeout: float = 29 * 60,
        reconnect_delay: float = 5.0,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._folder = folder
        self._subject_filter = subject_filter
        self._from_filter = from_filter
        self._use_ssl = use_ssl
        self._idle_timeout = idle_timeout
        self._reconnect_delay = reconnect_delay
        self._last_uid: int = 0

    # ── публичный streaming API ─────────────────────────────────────

    async def stream(self) -> AsyncIterator[EmailMessage]:
        """Бесконечный поток входящих писем через IMAP IDLE.

        Выполняет lazy-import ``aioimaplib``. При отсутствии библиотеки
        логирует предупреждение и завершается без ошибки.

        Yields:
            :class:`EmailMessage` для каждого нового письма, прошедшего фильтры.
        """
        try:
            import aioimaplib  # noqa: F401
        except ImportError:
            logger.warning(
                "EmailIMAPSource: aioimaplib не установлен — источник отключён. "
                "Установите: pip install aioimaplib"
            )
            return

        async for msg in self._idle_stream():
            yield msg

    # ── внутренние методы ───────────────────────────────────────────

    def _ssl_context(self) -> ssl.SSLContext:
        """Создаёт безопасный SSL-контекст (CERT_REQUIRED — обязательно).

        Returns:
            Настроенный :class:`ssl.SSLContext`.
        """
        ctx = ssl.create_default_context()
        # Явная проверка: запрещено CERT_NONE / check_hostname=False (V1)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        return ctx

    async def _connect(self) -> Any:
        """Устанавливает IMAP-соединение и логин.

        Returns:
            Авторизованный IMAP-клиент (``aioimaplib.IMAP4_SSL`` или ``IMAP4``).
        """
        from aioimaplib import IMAP4, IMAP4_SSL

        ssl_ctx = self._ssl_context()

        if self._use_ssl:
            client = IMAP4_SSL(host=self._host, port=self._port, ssl_context=ssl_ctx)
        else:
            client = IMAP4(host=self._host, port=self._port)

        await client.wait_hello_from_server()
        await client.login(self._user, self._password)
        await client.select(self._folder)
        return client

    def _matches(self, parsed: dict[str, str]) -> bool:
        """Применяет subject_filter и from_filter к распарсенному письму.

        Args:
            parsed: Словарь из :func:`_parse_raw_email`.

        Returns:
            True если письмо проходит все фильтры.
        """
        if self._subject_filter is not None:
            if self._subject_filter.lower() not in parsed.get("subject", "").lower():
                return False
        if self._from_filter is not None:
            if self._from_filter.lower() not in parsed.get("from", "").lower():
                return False
        return True

    async def _fetch_new_messages(self, client: Any) -> list[EmailMessage]:
        """Извлекает UNSEEN-письма, прошедшие фильтры, с сервера.

        Args:
            client: Авторизованный IMAP-клиент.

        Returns:
            Список новых :class:`EmailMessage`.
        """
        try:
            response = await client.search("UNSEEN")
        except Exception as exc:
            logger.warning("EmailIMAPSource: search UNSEEN failed: %s", exc)
            return []

        lines = response.lines or []
        raw_ids: list[str] = lines[0].decode().split() if lines and lines[0] else []

        result: list[EmailMessage] = []
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
                logger.warning("EmailIMAPSource: fetch %s failed: %s", msg_id, exc)
                continue

            raw_bytes = b""
            for line in fetch_resp.lines or []:
                if isinstance(line, (bytes, bytearray)) and len(line) > 100:
                    raw_bytes = bytes(line)
                    break
            if not raw_bytes:
                continue

            parsed = _parse_raw_email(raw_bytes)
            if not self._matches(parsed):
                logger.debug(
                    "EmailIMAPSource: UID=%s отфильтрован (subject=%r, from=%r)",
                    msg_id,
                    parsed.get("subject"),
                    parsed.get("from"),
                )
                continue

            email_msg = EmailMessage(
                uid=msg_id,
                subject=parsed.get("subject", ""),
                from_addr=parsed.get("from", ""),
                to_addr=parsed.get("to", ""),
                body=parsed.get("body", ""),
                received_at=datetime.now(UTC),
                headers={k: v for k, v in parsed.items() if k not in ("body",)},
            )
            result.append(email_msg)
            if uid:
                self._last_uid = max(self._last_uid, uid)

        return result

    async def _idle_stream(self) -> AsyncIterator[EmailMessage]:
        """Внутренний цикл IMAP IDLE с переподключением.

        Yields:
            :class:`EmailMessage` для каждого нового письма.
        """
        while True:
            try:
                client = await self._connect()
            except Exception as exc:
                logger.error(
                    "EmailIMAPSource: connect failed: %s — retry in %.1fs",
                    exc,
                    self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                continue

            try:
                # Первичный fetch — письма накопившиеся до старта.
                for msg in await self._fetch_new_messages(client):
                    yield msg

                while True:
                    try:
                        await client.idle_start(timeout=self._idle_timeout)
                        await client.wait_server_push()
                    except Exception as exc:
                        logger.warning(
                            "EmailIMAPSource: IDLE error: %s — reconnecting", exc
                        )
                        break
                    finally:
                        try:
                            client.idle_done()
                        except Exception as _:
                            logger.debug(
                                "EmailIMAPSource: idle_done failed", exc_info=True
                            )

                    for msg in await self._fetch_new_messages(client):
                        yield msg

            finally:
                try:
                    await client.logout()
                except Exception as _:
                    logger.debug("EmailIMAPSource: logout failed", exc_info=True)
