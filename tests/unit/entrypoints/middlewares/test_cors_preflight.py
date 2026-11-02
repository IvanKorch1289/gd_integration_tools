"""ADR-0422 — CORS preflight не должен требовать API-ключ.

Контекст дефекта
----------------
``OPTIONS /api/v1/invocations`` возвращал **401**: запрос доходил до
``APIKeyMiddleware`` (order 110) раньше, чем до ``CORSMiddleware``
(order 30 — при LIFO-семантике ``add_middleware`` меньший order означает
**внутренний** middleware). Кроме того, ``cors_origins`` по умолчанию был
пустым списком — даже если бы preflight доходил до CORS, браузер получил бы
``400 Disallowed CORS origin``.

Проверяется:

* preflight отвечает ``204`` + ``Access-Control-*`` **без** API-ключа;
* приложение (эндпоинт) preflight-запрос не достигает;
* запрещённый origin → ``400`` (не ``204``);
* CORS зарегистрирован **вне** auth-слоя в реальном реестре;
* ``APIKeyMiddleware`` пропускает ``OPTIONS``;
* список origins по умолчанию непустой.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware
from src.backend.entrypoints.middlewares.cors import PreflightCORSMiddleware
from src.backend.entrypoints.middlewares.registry import MiddlewareRegistry
from src.backend.entrypoints.middlewares.setup_middlewares import build_default_registry

_ORIGIN = b"http://localhost:8501"
_PREFLIGHT_HEADERS = [
    (b"origin", _ORIGIN),
    (b"access-control-request-method", b"POST"),
    (b"access-control-request-headers", b"x-api-key,content-type"),
]


async def _receive() -> Message:  # pragma: no cover - тело запроса не читается
    return {"type": "http.request", "body": b"", "more_body": False}


async def _drive(
    app: ASGIApp, *, method: str = "OPTIONS", headers=None
) -> list[Message]:
    """Прогнать HTTP-scope через app и собрать исходящие сообщения."""
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": "/api/v1/invocations",
        "headers": list(headers if headers is not None else _PREFLIGHT_HEADERS),
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


def _header(messages: list[Message], name: str) -> str | None:
    """Значение заголовка из ``http.response.start``."""
    for msg in messages:
        if msg["type"] == "http.response.start":
            for key, value in msg.get("headers", []):
                if key.lower() == name.lower().encode("latin-1"):
                    return value.decode("latin-1")
    return None


def _cors(app: ASGIApp) -> PreflightCORSMiddleware:
    """CORS-middleware с разрешённым origin (тестовые настройки)."""
    return PreflightCORSMiddleware(
        app,
        allow_origins=["http://localhost:8501"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-API-Key", "Content-Type", "Authorization"],
        allow_credentials=True,
        max_age=600,
    )


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
                    routes_without_api_key=["/health", "/docs"],
                    webhook_signature_secrets={},
                    webhook_signature_fail_closed=False,
                    api_key="secret",
                    api_key_admin_roles=["operator"],
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
class TestCorsPreflight:
    """Preflight-запрос не должен упираться в auth."""

    async def test_preflight_returns_204_without_api_key(self) -> None:
        """OPTIONS без ключа → 204 (а не 401)."""
        reached = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal reached
            reached = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        chain = _cors(APIKeyMiddleware(app))
        messages = await _drive(chain)

        assert _status(messages) == 204, "preflight обязан вернуть 204 без ключа"
        assert reached is False, "preflight не должен доходить до эндпоинта"

    async def test_preflight_has_cors_headers(self) -> None:
        """В ответе есть ``Access-Control-Allow-Origin``/``-Methods``."""

        async def app(
            scope: Scope, receive: Receive, send: Send
        ) -> None:  # pragma: no cover
            await send({"type": "http.response.start", "status": 200, "headers": []})

        messages = await _drive(_cors(app))

        assert (
            _header(messages, "access-control-allow-origin") == "http://localhost:8501"
        )
        assert _header(messages, "access-control-allow-methods")
        assert _header(messages, "access-control-allow-headers")

    async def test_disallowed_origin_is_rejected(self) -> None:
        """Чужой origin → 400 (информативный отказ CORS)."""

        async def app(
            scope: Scope, receive: Receive, send: Send
        ) -> None:  # pragma: no cover
            await send({"type": "http.response.start", "status": 200, "headers": []})

        headers = [
            (b"origin", b"http://evil.example"),
            (b"access-control-request-method", b"POST"),
        ]
        messages = await _drive(_cors(app), headers=headers)

        assert _status(messages) == 400

    async def test_api_key_middleware_skips_options(self) -> None:
        """``APIKeyMiddleware`` не отвечает 401 на OPTIONS."""
        reached = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal reached
            reached = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        with patch(
            "src.backend.entrypoints.middlewares.api_key.settings"
        ) as mock_settings:
            mock_settings.secure.routes_without_api_key = ["/health"]
            mock_settings.secure.api_key = "secret"
            mock_settings.secure.api_key_admin_roles = ["operator"]
            chain = APIKeyMiddleware(app)
            messages = await _drive(chain)

        assert _status(messages) == 200
        assert reached is True


@pytest.mark.unit
class TestCorsRegistryOrder:
    """Порядок middleware в реальном реестре."""

    def test_cors_is_outer_of_auth_layers(self) -> None:
        """CORS обязан быть выше api_key и auth_required (LIFO: выше — внешнее)."""
        orders = {spec.name: spec.order for spec in _built_registry().specs()}

        assert "cors" in orders
        assert orders["cors"] > orders["api_key"], (
            "CORS должен быть ВНЕ api_key, иначе preflight гасится 401"
        )
        assert orders["cors"] > orders["auth_required"]

    def test_cors_is_outer_of_csrf(self) -> None:
        """CSRF не должен обрывать preflight до CORS."""
        orders = {spec.name: spec.order for spec in _built_registry().specs()}
        assert orders["cors"] > orders["csrf"]


@pytest.mark.unit
class TestCorsOriginsConfiguration:
    """Origins конфигурируемы и не пусты по умолчанию."""

    def test_default_origins_are_not_empty(self) -> None:
        """Дефолтный список origins непустой (иначе любой preflight → 400)."""
        from src.backend.core.config.security import SecureSettings

        default = SecureSettings.model_fields["cors_origins"].get_default(
            call_default_factory=True
        )
        assert default, "cors_origins по умолчанию не должен быть пустым"

    def test_origins_are_configurable_via_env(self) -> None:
        """Список origins приходит из настроек (поле модели, не хардкод)."""
        from src.backend.core.config.security import SecureSettings

        assert "cors_origins" in SecureSettings.model_fields
        field = SecureSettings.model_fields["cors_origins"]
        assert field.description, "у origins должно быть описание для оператора"
