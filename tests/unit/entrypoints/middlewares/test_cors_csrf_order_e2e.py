"""ADR-0422 — E2E-проверка порядка CORS/CSRF/auth на РЕАЛЬНОЙ цепочке.

Контекст
--------
Юнит-тесты соседних волн проверяют порядок middleware по цифрам реестра и
по вручную собранным цепочкам. Этот файл закрывает оставшийся зазор:
проверяет **реальное поведение приложения** — с реальными настройками,
реальным реестром и реальным порядком регистрации.

Контракт (ADR-0422):

* ``OPTIONS`` без API-ключа → **204** + ``Access-Control-*``; эндпоинт не
  достигается (preflight не несёт credentials);
* ``POST`` без credentials → **401** (не 403 ``csrf_token_missing``);
* ``POST`` с API-ключом → запрос доходит до эндпоинта (CSRF не мешает
  token-auth);
* ответы с ошибкой аутентификации остаются читаемыми из браузера
  (``Access-Control-Allow-Origin`` присутствует);
* preflight с заголовком ``X-CSRF-Token`` разрешён (cookie-based CSRF
  не ломается о CORS).
"""

from __future__ import annotations

import hmac
import importlib
import pkgutil

import httpx
import pytest
from fastapi import FastAPI

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.config.secret import secret_value
from src.backend.core.config.settings import settings
from src.backend.entrypoints import middlewares as _middlewares
from src.backend.entrypoints.middlewares.setup_middlewares import setup_middlewares

#: Origin локального Streamlit — входит в дефолтный allowlist.
_ORIGIN = "http://localhost:8501"

# Тест строит приложение с РЕАЛЬНЫМИ middleware, поэтому импортируем все
# модули пакета на этапе collection — до того, как какой-либо тест подменит
# ``src.backend.core.config.settings.settings``. Middleware-модули делают
# ``from src.backend.core.config.settings import settings`` на уровне модуля,
# поэтому модуль, впервые импортированный под подменой, навсегда получает
# MagicMock вместо Settings (order-dependent pollution, ADR-0404).
for _module_info in pkgutil.iter_modules(_middlewares.__path__):
    importlib.import_module(f"{_middlewares.__name__}.{_module_info.name}")


@pytest.fixture(autouse=True)
def stub_auth_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменить credential-verifier на детерминированный API-key-stub.

    Тест проверяет **порядок слоёв** (CORS снаружи, CSRF внутри auth), а не
    реализацию верификаторов. Глобальный реестр верификаторов
    (``auth_selector._VERIFIERS``) загрязняется другими тестами
    (order-dependent pollution), поэтому API-key-ветка фиксируется здесь
    явно: валидный ``X-API-Key`` → контекст, всё остальное → ``None``.
    """

    async def _verify(request, methods=None):  # type: ignore[no-untyped-def]
        provided = request.headers.get("x-api-key", "")
        expected = secret_value(settings.secure.api_key)
        if provided and expected and hmac.compare_digest(provided, expected):
            return AuthContext(
                method=AuthMethod.API_KEY,
                principal="api_key_consumer",
                metadata={"tenant_id": "default"},
            )
        return None

    monkeypatch.setattr("src.backend.core.auth.auth_selector.verify_request", _verify)


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Приложение с реальной цепочкой middleware (реальные настройки)."""
    fastapi_app = FastAPI()

    @fastapi_app.api_route("/api/v1/invocations", methods=["GET", "POST"])
    async def invocations() -> dict[str, str]:
        return {"reached": "yes"}

    @fastapi_app.api_route("/api/v1/ai/chat", methods=["POST"])
    async def chat() -> dict[str, str]:
        return {"reached": "yes"}

    setup_middlewares(fastapi_app)
    return fastapi_app


@pytest.fixture
async def client(app: FastAPI):  # type: ignore[no-untyped-def]
    """httpx-клиент поверх ASGI-приложения (без сети)."""
    transport = httpx.ASGITransport(app=app)
    # Host из ``secure.allowed_hosts`` — иначе TrustedHostMiddleware отвечает
    # 400 «Invalid host header» до того, как запрос дойдёт до auth-слоя.
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as http_client:
        yield http_client


@pytest.mark.unit
class TestPreflightWithoutAuth:
    """Preflight не требует credentials."""

    async def test_options_without_api_key_returns_204(self, client) -> None:
        """OPTIONS без ключа → 204 (не 401)."""
        response = await client.request(
            "OPTIONS",
            "/api/v1/invocations",
            headers={
                "Origin": _ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key,content-type",
            },
        )

        assert response.status_code == 204, (
            f"preflight обязан вернуть 204, получено {response.status_code}"
        )
        assert response.headers.get("access-control-allow-origin") == _ORIGIN
        assert response.headers.get("access-control-allow-methods")

    async def test_preflight_with_csrf_header_is_allowed(self, client) -> None:
        """Preflight с ``X-CSRF-Token`` не отклоняется (400 → невалидный)."""
        response = await client.request(
            "OPTIONS",
            "/api/v1/ai/chat",
            headers={
                "Origin": _ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-csrf-token,content-type",
            },
        )

        assert response.status_code == 204, (
            "cookie-based CSRF-флоу требует X-CSRF-Token в allowlist заголовков"
        )

    async def test_preflight_does_not_reach_endpoint(self, client) -> None:
        """Preflight гасится CORS-слоем, эндпоинт не вызывается."""
        response = await client.request(
            "OPTIONS",
            "/api/v1/invocations",
            headers={"Origin": _ORIGIN, "Access-Control-Request-Method": "POST"},
        )

        assert response.status_code == 204
        assert "reached" not in response.text


@pytest.mark.unit
class TestMutationAuthCodes:
    """Мутации: нет credentials → 401, CSRF-ошибка → 403."""

    async def test_post_without_key_returns_401(self, client) -> None:
        """POST без ключа → 401 и без ``csrf_token_missing``."""
        response = await client.post("/api/v1/ai/chat", json={"message": "hi"})

        assert response.status_code == 401, (
            f"ожидался 401, получено {response.status_code}"
        )
        assert "csrf_token_missing" not in response.text

    async def test_401_response_is_readable_from_browser(self, client) -> None:
        """Ответ 401 остаётся читаемым из браузера (CORS-заголовки есть)."""
        response = await client.post(
            "/api/v1/ai/chat", json={"message": "hi"}, headers={"Origin": _ORIGIN}
        )

        assert response.status_code == 401
        assert response.headers.get("access-control-allow-origin") == _ORIGIN

    async def test_post_with_api_key_is_not_blocked_by_csrf(self, client) -> None:
        """POST с валидным API-ключом доходит до эндпоинта (CSRF-exempt)."""
        response = await client.post(
            "/api/v1/ai/chat",
            json={"message": "hi"},
            headers={"X-API-Key": secret_value(settings.secure.api_key)},
        )

        assert response.status_code == 200, (
            f"ожидался 200, получено {response.status_code}: {response.text[:200]}"
        )
        assert "csrf_token_missing" not in response.text
