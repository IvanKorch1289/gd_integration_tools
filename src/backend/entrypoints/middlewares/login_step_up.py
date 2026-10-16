"""Step-up auth middleware для ``POST /api/v1/auth/login`` (B-04, cycle 33 pure ASGI).

B-04 fix (cycle 33): ``/api/v1/auth/login`` УДАЛЁН из
``DEFAULT_PUBLIC_PATH_PREFIXES`` в :mod:`auth_required`. Этот middleware
перехватывает запрос на login и требует:

1. **Header ``X-Step-Up-Token``** — short-lived token, выданный
   pre-auth endpoint'ом (``/api/v1/auth/step-up-request``).
   Это защищает от credential stuffing без знания token'а.
2. **Rate-limit 10 attempts / 5 min per IP** — через существующий
   :class:`FakeRateLimitChecker` (in-memory, dev/test) или
   :class:`RedisRateLimitChecker` (prod, через ``build_rate_limit_checker``).

Поведение:

* ``POST /api/v1/auth/login`` без ``X-Step-Up-Token`` → 401 JSON.
* Превышение rate-limit → 429 + ``Retry-After``.
* ``OPTIONS`` preflight → пробрасывается downstream (CORS).
* Любой другой endpoint → пробрасывается downstream
  (этот middleware НЕ auth-guard для всех routes).

Pure ASGI (по образцу :mod:`security_headers`): оборачивает ``send``
НЕ нужно — ответы 401/429 отправляются напрямую. Non-HTTP scope
(``websocket`` / ``lifespan``) пробрасывается без проверок.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.entrypoints.middlewares.global_ratelimit import RateLimitChecker

__all__ = (
    "LOGIN_PATH",
    "LOGIN_RATE_LIMIT",
    "LOGIN_WINDOW_SECONDS",
    "STEP_UP_TTL_SECONDS",
    "LoginStepUpMiddleware",
    "issue_step_up_token",
    "validate_step_up_token",
)

_logger = get_logger("entrypoints.middlewares.login_step_up")

# Public constants (покрыты в тестах).
LOGIN_PATH = "/api/v1/auth/login"
LOGIN_RATE_LIMIT = 10
LOGIN_WINDOW_SECONDS = 300  # 5 min
STEP_UP_TTL_SECONDS = 600  # 10 min — жизнь X-Step-Up-Token.

# Параметр тунблирования через DI (для тестов).
DEFAULT_RATE_LIMIT_FACTORY: Callable[[], RateLimitChecker] | None = None


def _signing_key() -> bytes:
    """HMAC-ключ из SecureSettings.secret_key (тот же, что у JwtBackend)."""
    try:
        from src.backend.core.config.security import secure_settings

        secret = secure_settings.secret_key
        value = (
            secret.get_secret_value()
            if hasattr(secret, "get_secret_value")
            else str(secret)
        )
        return value.encode("utf-8")
    except Exception as exc:  # pragma: no cover — defensive (конфиг есть всегда)
        _logger.error("login_step_up.signing_key_unavailable: %s", exc)
        return b"login_step_up_fallback_key"


def issue_step_up_token(client_ip: str) -> tuple[str, int]:
    """Выпускает подписанный краткоживущий X-Step-Up-Token (B-04 completion).

    Формат: ``base64url(payload_json).hex_signature``; payload связывает
    клиентский IP + expiry (STEP_UP_TTL_SECONDS). Подпись — HMAC-SHA256
    от SecureSettings.secret_key.

    Returns:
        (token, ttl_seconds).

    """
    payload = {
        "ip": client_ip,
        "exp": int(time.time()) + STEP_UP_TTL_SECONDS,
        "nonce": uuid.uuid4().hex,
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    sig = hmac.new(
        _signing_key(), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}", STEP_UP_TTL_SECONDS


def validate_step_up_token(token: str, client_ip: str) -> bool:
    """Верифицирует X-Step-Up-Token: подпись, expiry, привязку к IP.

    Prod-fix 2026-09-09 (M6-#3): раньше проверялось только наличие
    header (presence-check) — любое non-empty значение проходило.
    """
    if not token:
        return False
    payload_b64, _, sig = token.partition(".")
    if not payload_b64 or not sig:
        return False
    expected = hmac.new(
        _signing_key(), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
    except ValueError, json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("ip") != client_ip:
        return False
    return int(payload.get("exp", 0)) >= int(time.time())


def _default_rate_limit_factory() -> RateLimitChecker:
    """Возвращает rate-limit checker (Redis prod / Fake dev).

    Использует существующую фабрику из :mod:`global_ratelimit`,
    которая автоматически выбирает Redis (prod) или Fake (dev/test).
    """
    from src.backend.entrypoints.middlewares.global_ratelimit import (
        FakeRateLimitChecker,
        build_rate_limit_checker,
    )

    try:
        return build_rate_limit_checker(
            max_per_window=LOGIN_RATE_LIMIT, window_seconds=float(LOGIN_WINDOW_SECONDS)
        )
    except Exception as exc:  # pragma: no cover — defensive
        _logger.warning(
            "login_step_up.rate_limit_factory_failed error=%r; falling back to Fake",
            exc,
        )
        return FakeRateLimitChecker(
            max_per_window=LOGIN_RATE_LIMIT, window_seconds=float(LOGIN_WINDOW_SECONDS)
        )


def _extract_client_ip(scope: Scope) -> str:
    """Извлекает client IP с учётом ``X-Forwarded-For``.

    За reverse proxy (nginx/ALB) — первый IP из XFF.
    Без proxy — ``scope['client'][0]``.
    """
    for header_name, header_value in scope.get("headers") or ():
        if header_name == b"x-forwarded-for":
            try:
                decoded = header_value.decode("latin-1")
            except UnicodeDecodeError:
                continue
            if decoded:
                return decoded.split(",")[0].strip()
    client = scope.get("client") or ("-", 0)
    host = client[0] if isinstance(client, (list, tuple)) else "-"
    return host if isinstance(host, str) else "-"


def _get_step_up_token(scope: Scope) -> str:
    """Извлекает значение ``X-Step-Up-Token`` (или пустую строку)."""
    for header_name, header_value in scope.get("headers") or ():
        if header_name == b"x-step-up-token":
            try:
                return header_value.decode("latin-1").strip()
            except UnicodeDecodeError:
                return ""
    return ""


class LoginStepUpMiddleware:
    """Pure ASGI middleware: step-up auth для ``POST /api/v1/auth/login``.

    B-04 fix (cycle 33): login endpoint защищён дополнительным
    ``X-Step-Up-Token`` header + per-IP rate-limit (10 / 5min).
    Не-auth-guard для остальных routes — только login.

    Поведение:

    1. Non-HTTP scope → пробрасывается downstream.
    2. ``OPTIONS`` preflight → пробрасывается downstream (CORS).
    3. Любой path кроме ``LOGIN_PATH`` → пробрасывается downstream.
    4. ``POST LOGIN_PATH`` без ``X-Step-Up-Token`` → 401 JSON.
    5. Превышение rate-limit → 429 + ``Retry-After``.
    6. Иначе → пробрасывается downstream к auth-логике.

    Args:
        app: Inner ASGI-приложение (FastAPI/Starlette).
        rate_limit_factory: Callable → ``RateLimitChecker``.
            Default — :func:`_default_rate_limit_factory`.

    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        rate_limit_factory: Callable[[], RateLimitChecker] | None = None,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            rate_limit_factory: Фабрика rate-limit checker'а.

        """
        self.app = app
        factory = rate_limit_factory or DEFAULT_RATE_LIMIT_FACTORY
        self._checker: RateLimitChecker = (
            factory() if factory is not None else _default_rate_limit_factory()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        B-04 fix (cycle 33): pure ASGI, no-raise pattern (cycle 39).
        На ошибках 401/429 — отвечает напрямую через ``send``.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        # CORS preflight — bypass.
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # Только login path защищается. Всё остальное — bypass.
        if path != LOGIN_PATH:
            await self.app(scope, receive, send)
            return

        # Только POST — login всегда POST. Прочие методы → 405-like bypass
        # (но это auth-method-handler territory, не middleware).
        if method != "POST":
            await self.app(scope, receive, send)
            return

        # 1. Step-up token: извлекаем, верифицируем подпись+expiry+IP.
        client_ip = _extract_client_ip(scope)
        token_value = _get_step_up_token(scope)
        if not validate_step_up_token(token_value, client_ip):
            _logger.warning(
                "login_step_up.invalid_or_missing_token path=%s ip=%s", path, client_ip
            )
            await _send_401(
                send,
                error="step_up_token_required",
                detail=(
                    "Valid X-Step-Up-Token required — obtain via "
                    "POST /api/v1/auth/step-up-request"
                ),
            )
            return

        # 2. Rate limit per-IP (10 attempts / 5 min).
        identifier = f"login_stepup:ip:{client_ip}"
        try:
            allowed, _remaining, retry_after = await self._checker.check(identifier)
        except Exception as exc:
            # Fail-closed для login: deny (anti-brute-force).
            _logger.error(
                "login_step_up.rate_limit_check_failed ip=%s error=%r — DENY",
                client_ip,
                exc,
            )
            await _send_429(
                send,
                retry_after=LOGIN_WINDOW_SECONDS,
                detail="Rate limit backend unavailable. Try again later.",
            )
            return

        if not allowed:
            _logger.warning(
                "login_step_up.rate_limit_exceeded ip=%s retry_after=%s",
                client_ip,
                retry_after,
            )
            await _send_429(
                send,
                retry_after=retry_after,
                detail="Too many login attempts. Retry later.",
            )
            return

        # 3. OK → пробрасываем downstream (auth-handler).
        await self.app(scope, receive, send)


async def _send_401(send: Send, *, error: str, detail: str) -> None:
    """Отправляет 401 JSON через send (no-raise, cycle 39)."""
    body_bytes = json.dumps({"error": error, "detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body_bytes)).encode("latin-1")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body_bytes})


async def _send_429(send: Send, *, retry_after: int, detail: str) -> None:
    """Отправляет 429 JSON с ``Retry-After`` (no-raise, cycle 39)."""
    body_bytes = json.dumps(
        {"error": "rate_limit_exceeded", "detail": detail, "retry_after": retry_after}
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body_bytes)).encode("latin-1")),
                (b"retry-after", str(retry_after).encode("latin-1")),
                (b"x-ratelimit-scope", b"login_step_up"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body_bytes})
