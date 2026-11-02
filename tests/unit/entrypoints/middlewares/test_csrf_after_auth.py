"""ADR-0422 — CSRF не должен обгонять аутентификацию.

Контекст дефекта
----------------
``POST /api/v1/ai/chat`` без ключа возвращал **403**
(``csrf_token_missing``) вместо **401**. Причина — порядок middleware:
``CSRFMiddleware`` стоял на ``order=740``, а ``AuthRequiredMiddleware`` — на
``order=620``. Из-за LIFO-семантики ``add_middleware`` **высокий order =
внешний**, то есть CSRF выполнялся РАНЬШЕ auth-guard'а и отвечал 403 ещё до
проверки credentials.

По контракту (ADR-0422):

* нет ключа → **401** (не «CSRF-ошибка»);
* аутентификация прошла, но CSRF-токена нет → **403** ``csrf_token_missing``.

Проверяется на реальном порядке middleware в реестре и на цепочке
``AuthRequiredMiddleware(CSRFMiddleware(app))``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.middlewares.registry import MiddlewareRegistry
from src.backend.entrypoints.middlewares.setup_middlewares import build_default_registry


async def _receive() -> Message:  # pragma: no cover - тело запроса не читается
    return {"type": "http.request", "body": b"", "more_body": False}


async def _drive(app: ASGIApp, *, method: str = "POST") -> list[Message]:
    """Прогнать HTTP-scope через app и собрать исходящие сообщения."""
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": "/api/v1/ai/chat",
        "headers": [],
    }
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, _receive, send)
    return sent


def _status(messages: list[Message]) -> int:
    """HTTP-статус из первого ``http.response.start``."""
    for msg in messages:
        if msg["type"] == "http.response.start":
            return int(msg["status"])
    return 0


def _body(messages: list[Message]) -> str:
    """Склеенное тело ответа."""
    return b"".join(
        msg.get("body", b"") for msg in messages if msg["type"] == "http.response.body"
    ).decode("utf-8", errors="replace")


def _chain() -> ASGIApp:
    """Цепочка auth → csrf → app, собранная из РЕАЛЬНОГО реестра.

    Порядок берётся из :func:`build_default_registry` — тест обязан ловить
    регрессию именно в регистрации middleware, а не в ручной сборке.
    """

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    specs = {spec.name: spec for spec in _built_registry().specs()}
    chain: ASGIApp = app
    # apply_to_app итерирует specs по возрастанию order, а add_middleware
    # делает insert(0) → последний зарегистрированный становится внешним.
    for name in sorted(("auth_required", "csrf"), key=lambda n: specs[n].order):
        spec = specs[name]
        chain = spec.middleware_cls(chain, **dict(spec.options))
    return chain


def _built_registry() -> MiddlewareRegistry:
    """Реальный реестр built-in middleware с замоканными settings."""
    real_registry = MiddlewareRegistry()
    with (
        patch(
            "src.backend.entrypoints.middlewares.registry.MiddlewareRegistry",
            return_value=real_registry,
        ),
        patch(
            "src.backend.core.config.settings.settings",
            MagicMock(
                secure=MagicMock(
                    cors_origins=["http://localhost:8501"],
                    cors_allow_credentials=True,
                    cors_allow_methods=["GET", "POST", "OPTIONS"],
                    cors_allow_headers=["*"],
                    allowed_hosts=["*"],
                    csrf_enabled=True,
                ),
                app=MagicMock(
                    compression_brotli=False,
                    brotli_minimum_size=100,
                    brotli_quality=4,
                    gzip_minimum_size=500,
                    gzip_compresslevel=6,
                    title="test",
                ),
            ),
        ),
    ):
        build_default_registry()
    return real_registry


@pytest.mark.unit
class TestCsrfRunsAfterAuthentication:
    """CSRF отвечает 403 только после успешной аутентификации."""

    async def test_missing_credentials_gives_401(self) -> None:
        """Без ключа → 401, а не 403 csrf_token_missing."""
        messages = await _drive(_chain())

        assert _status(messages) == 401, "отсутствие ключа должно давать 401"
        assert "csrf_token_missing" not in _body(messages)

    async def test_authenticated_without_csrf_token_gives_403(self) -> None:
        """Аутентификация прошла, CSRF-токена нет → 403 csrf_token_missing."""
        ctx = AuthContext(
            method=AuthMethod.EXPRESS_JWT,
            principal="edge-proxy",
            metadata={"tenant_id": "default"},
        )
        with patch(
            "src.backend.core.auth.auth_selector.verify_request", return_value=ctx
        ):
            messages = await _drive(_chain())

        assert _status(messages) == 403
        assert "csrf_token_missing" in _body(messages)


@pytest.mark.unit
class TestCsrfRegistryOrder:
    """Порядок CSRF и auth-guard'а в реальном реестре."""

    def test_csrf_is_inner_of_auth_required(self) -> None:
        """CSRF выполняется ПОСЛЕ auth (LIFO: меньший order — внутренний)."""
        orders = {spec.name: spec.order for spec in _built_registry().specs()}

        assert "csrf" in orders
        assert orders["csrf"] < orders["auth_required"], (
            "CSRF должен быть ВНУТРИ auth_required, иначе он отвечает 403 "
            "раньше, чем auth-guard успеет ответить 401"
        )
