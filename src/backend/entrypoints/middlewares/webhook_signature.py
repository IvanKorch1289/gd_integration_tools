"""V9 HMAC-SHA256 middleware для входящих webhooks (Stripe-style).

Wave [s2/k1-4-webhook-sig]: консолидирует верификацию подписи в одном
месте, дропает inline-код в :mod:`infrastructure.sources.webhook`.

Поведение:
* path-prefix allowlist (например ``/webhooks/``);
* для каждого пути берётся secret из ``secrets_by_prefix``;
* считывает ``X-Webhook-Signature`` + ``X-Webhook-Timestamp``;
* делегирует :func:`signatures.verify_signature` (canonical HMAC-SHA256).
* при провале возвращает 401, не пропуская дальше.

Пути вне prefix-allowlist обрабатываются без проверки.
"""

from __future__ import annotations

import logging
from typing import Mapping

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.backend.infrastructure.security.signatures import (
    DEFAULT_TIMESTAMP_WINDOW,
    verify_signature,
)

__all__ = ("WebhookSignatureMiddleware",)

_logger = logging.getLogger(__name__)


class WebhookSignatureMiddleware(BaseHTTPMiddleware):
    """V9 Stripe-style HMAC верификация для входящих webhooks.

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
        super().__init__(app)
        self._prefixes = tuple(path_prefixes)
        self._secrets = dict(secrets_by_prefix or {})
        self._sig_header = signature_header
        self._ts_header = timestamp_header
        self._window = timestamp_window

    def _resolve_secret(self, path: str) -> str | None:
        """Возвращает наиболее специфичный secret для ``path`` или ``None``."""
        # Сортируем prefixes по длине убыванию — самый специфичный первым.
        for prefix in sorted(self._secrets, key=len, reverse=True):
            if path.startswith(prefix):
                return self._secrets[prefix]
        return None

    def _is_protected(self, path: str) -> bool:
        return any(path.startswith(p) for p in self._prefixes)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        if not self._is_protected(request.url.path):
            return await call_next(request)

        secret = self._resolve_secret(request.url.path)
        if secret is None:
            # Префикс protected, но secret не сконфигурирован: skip-verify
            # с warning'ом — это разрешает тестовые webhooks без подписи,
            # но в prod-конфигурации не должно встречаться.
            _logger.debug(
                "WebhookSignatureMiddleware: no secret for path=%s, skipping",
                request.url.path,
            )
            return await call_next(request)

        signature = request.headers.get(self._sig_header)
        timestamp_raw = request.headers.get(self._ts_header)
        if not signature or not timestamp_raw:
            return JSONResponse(
                {"detail": "Webhook signature headers missing"},
                status_code=401,
            )
        try:
            timestamp = int(timestamp_raw)
        except ValueError:
            return JSONResponse(
                {"detail": "Invalid timestamp header"}, status_code=401
            )

        # Body нужен полностью — сохраняем в state, чтобы downstream
        # endpoint мог прочитать через request.body() ещё раз.
        body = await request.body()

        if not verify_signature(
            body, signature, timestamp, secret, window_seconds=self._window
        ):
            return JSONResponse(
                {"detail": "Webhook signature invalid"}, status_code=401
            )

        # Кладём body обратно через scope-receive, чтобы handler смог прочитать.
        async def _receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]
        return await call_next(request)
