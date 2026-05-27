"""Sprint 3 (V16.1 P1) — :class:`EmailSource`.

Полноценный Source для IMAP-ящиков. Отличия от
:class:`entrypoints.email.imap_monitor.ImapMonitor`:

* Реализует контракт :class:`Source` (`start`/`stop`/`health`) и эмитит
  :class:`SourceEvent` через ``on_event`` callback — больше не дёргает
  ``DSLService.dispatch`` напрямую.
* Поддерживает IMAP IDLE-режим (быстрая реакция на новые письма) с
  fallback на polling, если ``idle_mode=False`` или сервер не поддерживает.
* Фильтры по теме (`subject_pattern` substring/regex) и по отправителю
  (`from_filter` substring) применяются до эмита события.
* Использует :func:`get_task_registry` для leak-prevention asyncio-задач.

Реальные IMAP-операции и парсинг писем переиспользуют утилиту из
``infrastructure.sources.email_utils.parse_email`` (S27 refactoring).
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.sources.email_utils import parse_email
from src.backend.infrastructure.sources._lifecycle import graceful_cancel

if TYPE_CHECKING:
    pass

__all__ = ("EmailSource", "EmailSourceConfig")

logger = logging.getLogger("infrastructure.sources.email")


@dataclass(slots=True)
class EmailSourceConfig:
    """Параметры подключения и фильтрации EmailSource.

    Args:
        host: IMAP-сервер.
        port: Порт (993 IMAPS / 143 IMAP+STARTTLS).
        username: Логин.
        password: Пароль (только для dev). В prod — ``password_vault_ref``.
        password_vault_ref: Ссылка ``vault:<path>#<key>`` (см.
            :class:`VaultSecretRefresher`). Имеет приоритет над ``password``.
        folder: IMAP-папка для мониторинга (default ``INBOX``).
        use_ssl: Использовать IMAPS (port 993).
        starttls: Применить STARTTLS на plain-IMAP (если ``use_ssl=False``).
        verify_cert: Проверять серверный сертификат.
        idle_mode: Использовать IMAP IDLE (event-driven). Иначе — polling.
        idle_timeout: Таймаут одной IDLE-сессии в секундах
            (RFC 2177 рекомендует ≤ 29 минут).
        poll_interval: Интервал polling-fallback (сек).
        subject_pattern: Substring или regex (если строка начинается с
            ``re:``). ``None`` — без фильтра по теме.
        from_filter: Substring для From-заголовка. ``None`` — без фильтра.
        since_uid: Нижняя граница UID — фильтрует уже обработанные письма
            при перезапуске Source.
    """

    host: str
    port: int = 993
    username: str = ""
    password: str = ""
    password_vault_ref: str = ""
    folder: str = "INBOX"
    use_ssl: bool = True
    starttls: bool = True
    verify_cert: bool = True
    idle_mode: bool = True
    idle_timeout: float = 29 * 60
    poll_interval: float = 60.0
    subject_pattern: str | None = None
    from_filter: str | None = None
    since_uid: int = 0


class EmailSource:
    """IMAP-источник: эмитит ``SourceEvent`` для каждого нового письма.

    Реализация Protocol-совместима с :class:`Source` (см.
    :mod:`core.interfaces.source`).
    """

    kind: SourceKind = SourceKind.EMAIL

    def __init__(
        self,
        source_id: str,
        *,
        host: str,
        port: int = 993,
        username: str = "",
        password: str = "",
        password_vault_ref: str = "",
        folder: str = "INBOX",
        use_ssl: bool = True,
        starttls: bool = True,
        verify_cert: bool = True,
        idle_mode: bool = True,
        idle_timeout: float = 29 * 60,
        poll_interval: float = 60.0,
        subject_pattern: str | None = None,
        from_filter: str | None = None,
        since_uid: int = 0,
    ) -> None:
        self.source_id = source_id
        self._cfg = EmailSourceConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            password_vault_ref=password_vault_ref,
            folder=folder,
            use_ssl=use_ssl,
            starttls=starttls,
            verify_cert=verify_cert,
            idle_mode=idle_mode,
            idle_timeout=idle_timeout,
            poll_interval=poll_interval,
            subject_pattern=subject_pattern,
            from_filter=from_filter,
            since_uid=since_uid,
        )
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._subject_re = self._compile_subject_pattern(subject_pattern)
        self._last_uid: int = since_uid

    async def start(self, on_event: EventCallback) -> None:
        """Запустить приём писем (IDLE или polling — по конфигу)."""
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"EmailSource(id={self.source_id!r}) уже запущен")
        self._stopped.clear()
        self._task = get_task_registry().create_task(
            self._run(on_event), name=f"source-email:{self.source_id}"
        )
        logger.info(
            "EmailSource started: id=%s host=%s folder=%s idle=%s",
            self.source_id,
            self._cfg.host,
            self._cfg.folder,
            self._cfg.idle_mode,
        )

    async def stop(self) -> None:
        """Остановить приём, отменить задачу."""
        self._stopped.set()
        await graceful_cancel(self._task, source_id=self.source_id)
        self._task = None
        logger.info("EmailSource stopped: id=%s", self.source_id)

    async def health(self) -> bool:
        """Health: задача жива и не упала."""
        return self._task is not None and not self._task.done()

    # ──────────────── filter helpers ────────────────────────────────────

    @staticmethod
    def _compile_subject_pattern(pattern: str | None) -> re.Pattern[str] | None:
        """Превращает ``subject_pattern`` в regex-объект.

        Префикс ``re:`` → regex; иначе — literal substring (escape).
        """
        if not pattern:
            return None
        if pattern.startswith("re:"):
            return re.compile(pattern[3:], flags=re.IGNORECASE)
        return re.compile(re.escape(pattern), flags=re.IGNORECASE)

    def _match_subject(self, subject: str) -> bool:
        if self._subject_re is None:
            return True
        return bool(self._subject_re.search(subject))

    def _match_from(self, sender: str) -> bool:
        if not self._cfg.from_filter:
            return True
        return self._cfg.from_filter.lower() in sender.lower()

    def matches(self, message: dict[str, Any]) -> bool:
        """Применяет subject + from фильтры к распарсенному письму."""
        return self._match_subject(
            str(message.get("subject", ""))
        ) and self._match_from(str(message.get("from", "")))

    # ──────────────── credentials & ssl ────────────────────────────────

    async def _resolve_password(self) -> str:
        """Возвращает пароль — Vault ref или config.password."""
        ref = self._cfg.password_vault_ref
        if ref:
            try:
                from src.backend.core.di.providers import get_vault_refresher_provider

                refresher = get_vault_refresher_provider()
                return await refresher.resolve(ref)
            except Exception as exc:
                logger.error(
                    "EmailSource(%s): Vault-resolve fail (%s): %s — fallback to password",
                    self.source_id,
                    ref,
                    exc,
                )
        return self._cfg.password

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not (self._cfg.use_ssl or self._cfg.starttls):
            return None
        ctx = ssl.create_default_context()
        if not self._cfg.verify_cert:
            logger.warning(
                "EmailSource(%s): verify_cert=False игнорируется (V1 policy: "
                "ssl.CERT_NONE / check_hostname=False запрещены). "
                "Используйте кастомный CA через secrets capability.",
                self.source_id,
            )
        return ctx

    # ──────────────── main loops ───────────────────────────────────────

    async def _run(self, on_event: EventCallback) -> None:
        """Главный цикл: IDLE или polling."""
        try:
            from aioimaplib import IMAP4, IMAP4_SSL  # noqa: F401
        except ImportError:
            logger.warning(
                "EmailSource(%s): aioimaplib не установлен — источник отключён",
                self.source_id,
            )
            return

        if self._cfg.idle_mode:
            await self._idle_loop(on_event)
        else:
            await self._poll_loop(on_event)

    async def _connect(self) -> Any:
        """Создаёт и логинит IMAP-клиент."""
        from aioimaplib import IMAP4, IMAP4_SSL

        password = await self._resolve_password()
        ssl_ctx = self._ssl_context()

        if self._cfg.use_ssl:
            client = IMAP4_SSL(
                host=self._cfg.host, port=self._cfg.port, ssl_context=ssl_ctx
            )
        else:
            client = IMAP4(host=self._cfg.host, port=self._cfg.port)

        await client.wait_hello_from_server()
        if (not self._cfg.use_ssl) and self._cfg.starttls:
            await client.starttls(ssl_context=ssl_ctx)
        await client.login(self._cfg.username, password)
        await client.select(self._cfg.folder)
        return client

    async def _idle_loop(self, on_event: EventCallback) -> None:
        """IMAP IDLE: ожидает push от сервера, при событии — fetch UNSEEN."""
        while not self._stopped.is_set():
            try:
                client = await self._connect()
            except Exception as exc:
                logger.error(
                    "EmailSource(%s) connect failed: %s — retry in %.1fs",
                    self.source_id,
                    exc,
                    self._cfg.poll_interval,
                )
                await asyncio.sleep(self._cfg.poll_interval)
                continue

            try:
                # Первичный fetch — забираем существующие UNSEEN.
                await self._fetch_and_emit(client, on_event)

                while not self._stopped.is_set():
                    try:
                        await client.idle_start(timeout=self._cfg.idle_timeout)
                        await client.wait_server_push()
                    except Exception as exc:
                        logger.warning(
                            "EmailSource(%s) IDLE error: %s — reconnecting",
                            self.source_id,
                            exc,
                        )
                        break
                    finally:
                        try:
                            client.idle_done()
                        except Exception as _:
                            logger.debug(
                                "EmailSource(%s): idle_done failed",
                                self.source_id,
                                exc_info=True,
                            )
                    await self._fetch_and_emit(client, on_event)
            finally:
                try:
                    await client.logout()
                except Exception as _:
                    logger.debug(
                        "EmailSource(%s): logout failed", self.source_id, exc_info=True
                    )

    async def _poll_loop(self, on_event: EventCallback) -> None:
        """Polling-fallback: connect → fetch UNSEEN → close → sleep."""
        while not self._stopped.is_set():
            try:
                client = await self._connect()
                try:
                    await self._fetch_and_emit(client, on_event)
                finally:
                    try:
                        await client.logout()
                    except Exception as _:
                        logger.debug(
                            "EmailSource(%s): logout failed",
                            self.source_id,
                            exc_info=True,
                        )
            except Exception as _:
                logger.exception(
                    "EmailSource(%s): poll iteration failed", self.source_id
                )
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._cfg.poll_interval
                )
            except TimeoutError:
                continue

    # ──────────────── fetching ────────────────────────────────────────

    async def _fetch_and_emit(self, client: Any, on_event: EventCallback) -> None:
        """Извлекает UNSEEN-письма и эмитит события для прошедших фильтр."""
        try:
            response = await client.search("UNSEEN")
        except Exception as exc:
            logger.warning("EmailSource(%s) search failed: %s", self.source_id, exc)
            return

        lines = response.lines or []
        raw_ids = lines[0].decode().split() if lines and lines[0] else []
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
                logger.warning(
                    "EmailSource(%s): fetch %s failed: %s", self.source_id, msg_id, exc
                )
                continue

            raw_bytes = b""
            for line in fetch_resp.lines or []:
                if isinstance(line, (bytes, bytearray)) and len(line) > 100:
                    raw_bytes = bytes(line)
                    break
            if not raw_bytes:
                continue

            message = parse_email(raw_bytes)
            if not self.matches(message):
                logger.debug(
                    "EmailSource(%s): UID=%s отфильтрован (subject=%r, from=%r)",
                    self.source_id,
                    msg_id,
                    message.get("subject"),
                    message.get("from"),
                )
                continue

            event = SourceEvent(
                source_id=self.source_id,
                kind=self.kind,
                payload=message,
                event_time=datetime.now(UTC),
                metadata={
                    "uid": msg_id,
                    "folder": self._cfg.folder,
                    "x-source": "email_imap",
                    "x-email-from": message.get("from", ""),
                    "x-email-subject": message.get("subject", ""),
                },
            )
            try:
                await on_event(event)
            except Exception as exc:
                logger.error(
                    "EmailSource(%s): on_event failed (UID=%s): %s",
                    self.source_id,
                    msg_id,
                    exc,
                )
            else:
                if uid:
                    self._last_uid = max(self._last_uid, uid)
