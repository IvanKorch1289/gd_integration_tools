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

B-02 fix (cycle 33): fail-closed при отсутствии secret для protected
path-prefix. Раньше middleware skip-verify с ``logger.debug`` и
пропускал downstream — это давало обход подписи в любой среде, где
оператор забыл сконфигурировать ``secrets_by_prefix``. Теперь
возвращается 503 ``{"error":"webhook_not_configured"}`` и
инкрементируется ``webhook_signature_missing_secret_total{path_prefix}``.
Dev escape: passthrough допустим только при ``APP_ENVIRONMENT=dev``
И ``WEBHOOK_ALLOW_MISSING_SECRET=true`` (явный opt-in).

B-14 fix (cycle 36): webhook_signature 503 → unified error envelope.
503 response теперь формируется через ``build_error_envelope`` из
:mod:`src.backend.core.errors` для унификации формата с остальными
middlewares (csrf, rpa, и т.п.). Поля ``code``, ``detail``, ``error_id``,
``correlation_id``, ``request_id`` присутствуют в JSON body. Старое
поле ``error`` сохранено как backward-compat alias на ``code``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.errors import build_error_envelope
from src.backend.core.logging import get_logger
from src.backend.core.observability.metrics import (
    webhook_signature_missing_secret_total,
)
from src.backend.services.security import DEFAULT_TIMESTAMP_WINDOW, verify_signature

__all__ = ("WebhookSignatureMiddleware",)

_logger = get_logger(__name__)

# Dev escape opt-in: пропуск webhook без secret разрешён только когда
# ОБА условия выполнены. ``APP_ENVIRONMENT=dev`` гарантирует, что escape
# не сработает в staging/production (даже если env var случайно выставлен
# при деплое из CI). ``WEBHOOK_ALLOW_MISSING_SECRET=true`` — explicit
# acknowledgment оператора, что он понимает риск (без подписи запросы
# доходят до downstream handler'а).
_DEV_ENV_VALUE = "dev"
_WEBHOOK_ALLOW_ENV = "WEBHOOK_ALLOW_MISSING_SECRET"


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

    def _matched_path_prefix(self, path: str) -> str:
        """Самый специфичный (самый длинный) matched path_prefix для метрики."""
        matches = [p for p in self._prefixes if path.startswith(p)]
        return max(matches, key=len) if matches else ""

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
            # B-02 fix (cycle 33): fail-closed. Protected path-prefix без
            # сконфигурированного secret раньше skip-verify с debug-логом
            # — это давало обход подписи при drift конфигурации. Теперь
            # 503 + метрика. Dev escape требует явного opt-in через
            # ``APP_ENVIRONMENT=dev`` + ``WEBHOOK_ALLOW_MISSING_SECRET=true``.
            matched_prefix = self._matched_path_prefix(path)
            webhook_signature_missing_secret_total.labels(
                path_prefix=matched_prefix
            ).inc()
            if self._is_dev_escape_allowed():
                _logger.warning(
                    "WebhookSignatureMiddleware: no secret for path=%s "
                    "prefix=%s — dev escape active, passthrough",
                    path,
                    matched_prefix,
                )
                await self.app(scope, receive, send)
                return
            _logger.error(
                "WebhookSignatureMiddleware: no secret for path=%s "
                "prefix=%s — fail-closed 503",
                path,
                matched_prefix,
            )
            await self._send_503(
                send,
                detail=(
                    f"Webhook secret not configured for path prefix {matched_prefix!r}"
                ),
                scope=scope,
            )
            return

        # Читаем signature + timestamp headers (case-insensitive).
        sig_value = _get_header(scope, self._sig_header_lower)
        ts_value = _get_header(scope, self._ts_header_lower)
        if not sig_value or not ts_value:
            await self._send_401(send, detail="Webhook signature headers missing")
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
                return {"type": "http.request", "body": body, "more_body": False}
            # После первого запроса — disconnect (no more body).
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    def _is_dev_escape_allowed() -> bool:
        """Возвращает True только если dev-режим И opt-in env var выставлены.

        Двойная проверка защищает от случайного включения escape в
        staging/production через унаследованный env var из CI/CD.
        """
        env_value = os.environ.get("APP_ENVIRONMENT", "").strip().lower()
        allow_value = os.environ.get(_WEBHOOK_ALLOW_ENV, "").strip().lower() == "true"
        return env_value == _DEV_ENV_VALUE and allow_value

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

    @staticmethod
    async def _send_503(send: Send, *, detail: str, scope: Scope | None = None) -> None:
        """Отправляет 503 JSON response через send (B-02 fix, cycle 33).

        B-14 fix (cycle 36): webhook_signature 503 → unified error envelope.
        Использует ``build_error_envelope`` для унификации формата с
        остальными middlewares (csrf, rpa, и т.п.). Старый формат
        ``{"error","detail"}`` помечен как backward-compat alias в
        ``body["error"]`` для legacy clients.
        """
        body = build_error_envelope(
            code="webhook_not_configured", detail=detail, scope=scope
        )
        body["error"] = body["code"]  # backward-compat alias для legacy clients
        body_bytes = json.dumps(body).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Извлекает header из ASGI scope по lowercase bytes-имени."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None
