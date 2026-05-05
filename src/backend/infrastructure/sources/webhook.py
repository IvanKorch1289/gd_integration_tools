"""W23.5 — :class:`WebhookSource`.

HTTP-source с проверкой HMAC и timestamp-window против replay-атак.
Не привязывается к FastAPI напрямую: предоставляет
:meth:`verify_and_dispatch`, который вызывает router
``entrypoints/webhook/sources_router.py`` для каждого зарегистрированного
``WebhookSource``.

Безопасность:

* HMAC-SHA256 от raw body; константное время сравнения через ``hmac.compare_digest``.
* Опциональное timestamp-окно: ``X-Timestamp`` (unix-секунды) должен
  отличаться от ``time.time()`` не более чем на ``timestamp_window_seconds``.
* IP-allowlist оставлен на уровне сети/CDN — Source не дублирует.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.core.interfaces.source import EventCallback, SourceEvent, SourceKind

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ("WebhookSource", "WebhookVerificationError")

logger = logging.getLogger("infrastructure.sources.webhook")


class WebhookVerificationError(Exception):
    """Поднимается при невалидной HMAC-подписи или просроченном timestamp."""


class WebhookSource:
    """Универсальный inbound webhook (W23.5).

    Args:
        source_id: Уникальный id (используется в SourceRegistry).
        path: HTTP-путь (например ``/webhooks/orders/payment``).
        hmac_secret: Общий секрет для HMAC-SHA256. ``None`` → без проверки.
        hmac_header: Имя header'а с подписью (default ``X-Signature``).
        timestamp_header: Имя header'а с unix timestamp; если задан —
            включается timestamp-window check против replay.
        timestamp_window_seconds: Допустимое отклонение timestamp от
            ``time.time()`` (default 300с).
    """

    kind: SourceKind = SourceKind.WEBHOOK

    def __init__(
        self,
        source_id: str,
        *,
        path: str,
        hmac_secret: str | None = None,
        hmac_header: str = "X-Signature",
        timestamp_header: str | None = None,
        timestamp_window_seconds: float = 300.0,
    ) -> None:
        self.source_id = source_id
        self.path = path
        self._hmac_secret = hmac_secret.encode() if hmac_secret else None
        self._hmac_header = hmac_header
        self._ts_header = timestamp_header
        self._ts_window = timestamp_window_seconds
        self._on_event: EventCallback | None = None
        self._lock = asyncio.Lock()

    async def start(self, on_event: EventCallback) -> None:
        """Регистрирует callback. Повторный start без stop → ``RuntimeError``."""
        async with self._lock:
            if self._on_event is not None:
                raise RuntimeError(f"WebhookSource(id={self.source_id!r}) уже запущен")
            self._on_event = on_event
        logger.info("WebhookSource started: id=%s path=%s", self.source_id, self.path)

    async def stop(self) -> None:
        async with self._lock:
            self._on_event = None
        logger.info("WebhookSource stopped: id=%s", self.source_id)

    async def health(self) -> bool:
        return self._on_event is not None

    # ──────────────── Public verify+dispatch (вызывается из FastAPI router) ─

    def _verify_hmac(self, raw_body: bytes, headers: Mapping[str, str]) -> None:
        if self._hmac_secret is None:
            return
        signature = headers.get(self._hmac_header, "")
        expected = hmac.new(self._hmac_secret, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise WebhookVerificationError("HMAC signature mismatch")

    def _verify_timestamp(self, headers: Mapping[str, str]) -> float | None:
        if self._ts_header is None:
            return None
        raw = headers.get(self._ts_header)
        if raw is None:
            raise WebhookVerificationError(
                f"Required timestamp header {self._ts_header!r} missing"
            )
        try:
            ts = float(raw)
        except ValueError as exc:
            raise WebhookVerificationError(f"Invalid timestamp value: {raw!r}") from exc
        if abs(time.time() - ts) > self._ts_window:
            raise WebhookVerificationError(
                f"Timestamp drift exceeds window of {self._ts_window}s"
            )
        return ts

    async def verify_and_dispatch(
        self, raw_body: bytes, headers: Mapping[str, str], *, payload: Any = None
    ) -> None:
        """Проверить HMAC/timestamp и эмитить ``SourceEvent``.

        Args:
            raw_body: Сырое тело запроса (для HMAC).
            headers: HTTP headers (case-insensitive ожидается у вызывающего).
            payload: Распарсенный payload (если уже декодирован вызывающим).
        """
        if self._on_event is None:
            raise RuntimeError(
                f"WebhookSource(id={self.source_id!r}) не запущен (start не был вызван)"
            )
        self._verify_hmac(raw_body, headers)
        ts = self._verify_timestamp(headers)
        event_time = (
            datetime.fromtimestamp(ts, tz=UTC) if ts is not None else datetime.now(UTC)
        )
        event = SourceEvent(
            source_id=self.source_id,
            kind=self.kind,
            payload=payload,
            event_time=event_time,
            metadata={"headers": dict(headers)},
        )
        await self._on_event(event)
