"""V9 HMAC-SHA256 middleware для входящих webhooks (Stripe-style, cycle 44 pure ASGI).

Wave [s2/k1-4-webhook-sig]: консолидирует верификацию подписи в одном
месте, дропает inline-код в :mod:`infrastructure.sources.webhook`.

Поведение:
* path-prefix allowlist (например ``/webhooks/``);
* для каждого пути берётся secret из ``secrets_by_prefix``;
* считывает ``X-Webhook-Signature`` + ``X-Webhook-Timestamp``;
* делегирует :func:`signatures.verify_signature` (canonical HMAC-SHA256).
* при провале отправляет 401 через send (no-raise, cycle 39).

Пути вне prefix-allowlist обрабатываются без проверки.

Cycle 44: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-43 (L1 middlewares).

Cycle 44 critical: body buffering. Webhook signature verify требует
ПОЛНОГО body ДО передачи в downstream (HMAC нужен все байты). В
BaseHTTPMiddleware body уже buffered. В pure ASGI body приходит
через receive() chunks — middleware буферизует, верифицирует, и
``_receive`` re-injects body для downstream handlers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.logging import get_logger
from src.backend.services.security import DEFAULT_TIMESTAMP_WINDOW, verify_signature

__all__ = ("WebhookSignatureMiddleware",)

_logger = get_logger(__name__)


class WebhookSignatureMiddleware:
    """V9 Stripe-style HMAC верификация для входящих webhooks (cycle 44 pure ASGI).

    Args:
        app: ASGI-приложение.
        path_prefixes: Префиксы путей, для которых нужна верификация.
            Например ``("/webhooks/",)``. Пути вне списка пропускаются.
        secrets_by_prefix: Маппинг ``<prefix> → <secret>``.
        signature_header: Имя header'а с подписью (default ``X-Webhook-Signature``).
        timestamp_header: Имя header'а с timestamp (default ``X-Webhook-Timestamp``).
        timestamp_window: Окно валидности timestamp (default 300с).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        path_prefixes: tuple[str, ...] = ("/webhooks/",),
        secrets_by_prefix: Mapping[str, str] | None = None,
        signature_header: str = "X-Webhook-Signature",
        timestamp_header: str = "X-Webhook-Timestamp",
        timestamp_window: int = DEFAULT_TIMESTAMP_WINDOW,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            path_prefixes: Префиксы путей для верификации.
            secrets_by_prefix: Маппинг prefix → secret.
            signature_header: Имя header'а с подписью.
            timestamp_header: Имя header'а с timestamp.
            timestamp_window: Окно валидности timestamp.
        """
        self.app = app
        self._prefixes = tuple(path_prefixes)
        self._secrets = dict(secrets_by_prefix or {})
        self._sig_header = signature_header
        self._sig_header_lower = signature_header.lower().encode("latin-1")
        self._ts_header = timestamp_header
        self._ts_header_lower = timestamp_header.lower().encode("latin-1")
        self._window = timestamp_window

    def _resolve_secret(self, path: str) -> str | None:
        """Возвращает наиболее специфичный secret для ``path`` или ``None``."""
        for prefix in sorted(self._secrets, key=len, reverse=True):
            if path.startswith(prefix):
                return self._secrets[prefix]
        return None

    def _is_protected(self, path: str) -> bool:
        return any(path.startswith(p) for p in self._prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream без проверки подписи.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Path не protected → пробрасываем без verify.
        if not self._is_protected(path):
            await self.app(scope, receive, send)
            return

        secret = self._resolve_secret(path)
        if secret is None:
            # Префикс protected, но secret не сконфигурирован: skip-verify
            # с warning'ом — это разрешает тестовые webhooks без подписи,
            # но в prod-конфигурации не должно встречаться.
            _logger.debug(
                "WebhookSignatureMiddleware: no secret for path=%s, skipping",
                path,
            )
            await self.app(scope, receive, send)
            return

        # Читаем signature + timestamp headers (case-insensitive).
        sig_value = _get_header(scope, self._sig_header_lower)
        ts_value = _get_header(scope, self._ts_header_lower)
        if not sig_value or not ts_value:
            await self._send_401(
                send, detail="Webhook signature headers missing"
            )
            return

        try:
            timestamp = int(ts_value)
        except ValueError:
            await self._send_401(send, detail="Invalid timestamp header")
            return

        # Cycle 44 critical: буферизуем body полностью (HMAC нужен все байты).
        # В pure ASGI body приходит через receive() chunks — собираем их.
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                # Client disconnected — не можем верифицировать body.
                return
            body_chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        body = b"".join(body_chunks)

        if not verify_signature(
            body, sig_value, timestamp, secret, window_seconds=self._window
        ):
            await self._send_401(send, detail="Webhook signature invalid")
            return

        # Re-inject body для downstream handlers через новый receive.
        # ASGI protocol: receive() возвращает http.request с body.
        body_sent = False

        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            # После первого запроса — disconnect (no more body).
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_401(send: Send, *, detail: str) -> None:
        """Отправляет 401 JSON response через send (cycle 39 lesson)."""
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Извлекает header из ASGI scope по lowercase bytes-имени."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None
