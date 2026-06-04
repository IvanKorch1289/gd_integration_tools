# ruff: noqa: S101, SLF001
"""Smoke-тесты S39 W5 — модуль ``src.backend.plugins.composition.app_factory``.

Покрывают:
* публичный API модуля (``__all__``);
* сигнатуру ``create_app``;
* хелпер ``_configure_root_endpoint`` (root + liveness + readiness);
* хелпер ``_configure_business_routers`` (admin-legacy redirect, защита от open-redirect);
* хелпер ``_configure_auto_registered_actions`` (idempotency / graceful error);
* хелпер ``_configure_auto_graphql_schema`` (graceful error);
* хелпер ``_configure_application_components`` (mock-стек + graceful telemetry failure);
* re-export ``lifespan`` из ``lifecycle`` (smoke-проверка wiring'а).

Стратегия: каждое тест-кейс изолированно мокает network / DB зависимости
через ``monkeypatch.setattr`` или ``unittest.mock.patch``, чтобы избежать
реальных подключений к RabbitMQ / Postgres / Elasticsearch.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.plugins.composition import app_factory

# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_module_imports() -> None:
    """Модуль импортируется без побочных эффектов."""
    assert app_factory is not None


def test_module_exposes_expected_public_api() -> None:
    """``__all__`` содержит ровно одну публичную функцию — ``create_app``."""
    assert app_factory.__all__ == ("create_app",)


def test_create_app_is_callable() -> None:
    """``create_app`` — обычная (не async) функция-фабрика."""
    assert callable(app_factory.create_app)
    import inspect

    assert not inspect.iscoroutinefunction(app_factory.create_app)


def test_create_app_has_docstring() -> None:
    """У ``create_app`` есть осмысленный docstring (>= 50 символов)."""
    assert app_factory.create_app.__doc__ is not None
    assert len(app_factory.create_app.__doc__) > 50
    assert "FastAPI" in app_factory.create_app.__doc__


def test_module_reexports_lifespan_from_lifecycle() -> None:
    """``lifespan`` re-exported из lifecycle-модуля (контракт для FastAPI)."""
    from src.backend.plugins.composition.lifecycle import lifespan

    assert app_factory.lifespan is lifespan


def test_module_exposes_required_router_reexports() -> None:
    """Все обязательные routers импортируются на уровне модуля (root imports)."""
    required = (
        "graphql_router",
        "proto_viewer_router",
        "soap_router",
        "sse_router",
        "webhook_router",
        "webhook_sources_router",
        "ws_router",
        "ws_invocations_router",
        "root_page",
        "get_v1_routers",
        "get_stream_client",
        "setup_middlewares",
        "setup_admin",
        "setup_monitoring",
        "setup_tracing",
    )
    for name in required:
        assert hasattr(app_factory, name), f"{name} missing from app_factory"


# --------------------------------------------------------------------------- #
# _configure_root_endpoint
# --------------------------------------------------------------------------- #


def test_configure_root_endpoint_attaches_three_routes() -> None:
    """``_configure_root_endpoint`` добавляет ровно 3 маршрута: /, /health, /ready."""
    app = FastAPI()
    initial_count = len(app.routes)

    app_factory._configure_root_endpoint(app)

    # +3: GET /, GET /health, GET /ready.
    assert len(app.routes) - initial_count == 3
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/" in paths
    assert "/health" in paths
    assert "/ready" in paths


def test_configure_root_endpoint_liveness_returns_alive() -> None:
    """``GET /health`` возвращает ``{status: alive, version: ...}`` со 200."""
    app = FastAPI()
    app_factory._configure_root_endpoint(app)

    client = TestClient(app)
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "alive"
    assert "version" in body


def test_configure_root_endpoint_root_returns_html() -> None:
    """``GET /`` возвращает HTML-страницу (root_page)."""
    app = FastAPI()
    app_factory._configure_root_endpoint(app)

    client = TestClient(app)
    resp = client.get("/")

    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_configure_root_endpoint_readiness_healthy_returns_200() -> None:
    """``GET /ready`` со здоровым aggregator → 200."""
    app = FastAPI()
    app_factory._configure_root_endpoint(app)

    fake_agg = MagicMock()
    fake_agg.check_all = AsyncMock(return_value={"status": "ok"})

    with patch(
        "src.backend.infrastructure.application.health_aggregator.get_health_aggregator",
        return_value=fake_agg,
    ):
        client = TestClient(app)
        resp = client.get("/ready")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    fake_agg.check_all.assert_awaited_once()


def test_configure_root_endpoint_readiness_unhealthy_returns_503() -> None:
    """``GET /ready`` с degraded aggregator → 503 + payload."""
    app = FastAPI()
    app_factory._configure_root_endpoint(app)

    fake_agg = MagicMock()
    fake_agg.check_all = AsyncMock(
        return_value={"status": "degraded", "failures": ["x"]}
    )

    with patch(
        "src.backend.infrastructure.application.health_aggregator.get_health_aggregator",
        return_value=fake_agg,
    ):
        client = TestClient(app)
        resp = client.get("/ready")

    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


# --------------------------------------------------------------------------- #
# _configure_business_routers: admin_legacy_redirect
# --------------------------------------------------------------------------- #


@contextmanager
def _patched_business_routers() -> Any:
    """Контекст-менеджер: глушит ВСЕ тяжёлые зависимости _configure_business_routers."""
    stream = MagicMock()
    stream.redis_router = None
    stream.rabbit_router = None

    with patch(
        "src.backend.plugins.composition.app_factory.get_stream_client",
        return_value=stream,
    ):
        with patch(
            "src.backend.plugins.composition.app_factory.get_v1_routers",
            return_value=MagicMock(),
        ):
            with patch(
                "src.backend.plugins.composition.app_factory._configure_auto_registered_actions"
            ):
                with patch(
                    "src.backend.plugins.composition.app_factory._configure_auto_graphql_schema"
                ):
                    yield


def test_configure_business_routers_admin_relative_path_redirects() -> None:
    """``/api/admin/<rel>`` → 303 → ``/api/v1/admin/<rel>`` (preserve path)."""
    with _patched_business_routers():
        app = FastAPI()
        app_factory._configure_business_routers(app)

        client = TestClient(app)
        resp = client.get("/api/admin/users/42", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/api/v1/admin/users/42"


def test_configure_business_routers_admin_protocol_relative_blocked() -> None:
    """``/api/admin//evil.com/...`` → 400 (open-redirect protection)."""
    with _patched_business_routers():
        app = FastAPI()
        app_factory._configure_business_routers(app)

        client = TestClient(app)
        resp = client.get("/api/admin//evil.com/foo", follow_redirects=False)

    assert resp.status_code == 400
    assert "external" in resp.text.lower() or "invalid" in resp.text.lower()


def test_configure_business_routers_admin_post_preserves_method() -> None:
    """``POST /api/admin/foo`` → 303 redirect (303 — POST→GET, см. комментарий)."""
    with _patched_business_routers():
        app = FastAPI()
        app_factory._configure_business_routers(app)

        client = TestClient(app)
        resp = client.post("/api/admin/orders", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/api/v1/admin/orders"


# --------------------------------------------------------------------------- #
# _configure_auto_registered_actions
# --------------------------------------------------------------------------- #


def test_configure_auto_registered_actions_calls_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_configure_auto_registered_actions`` делегирует в ``auto_register_unrouted_actions``."""
    fake_app = MagicMock()
    called: dict[str, Any] = {}

    def _fake_auto(app: Any) -> int:
        called["app"] = app
        return 0

    monkeypatch.setattr(
        "src.backend.entrypoints.api.generator.auto_register.auto_register_unrouted_actions",
        _fake_auto,
    )
    # Регистрация action-handlers может бросить — но обёрнута в try/except.
    monkeypatch.setattr(
        "src.backend.dsl.commands.setup.register_action_handlers", lambda: None
    )

    app_factory._configure_auto_registered_actions(fake_app)

    assert called["app"] is fake_app


def test_configure_auto_registered_actions_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``auto_register_unrouted_actions`` падает — функция не валится (graceful)."""

    def _explode(_: Any) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(
        "src.backend.entrypoints.api.generator.auto_register.auto_register_unrouted_actions",
        _explode,
    )
    monkeypatch.setattr(
        "src.backend.dsl.commands.setup.register_action_handlers", lambda: None
    )

    # Не должно бросить.
    app_factory._configure_auto_registered_actions(MagicMock())


def test_configure_auto_registered_actions_survives_register_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``register_action_handlers`` падает — auto-loop всё равно отрабатывает."""
    called: dict[str, bool] = {"auto_called": False}

    def _fake_auto(_: Any) -> int:
        called["auto_called"] = True
        return 0

    def _explode() -> None:
        raise RuntimeError("simulated register failure")

    monkeypatch.setattr(
        "src.backend.entrypoints.api.generator.auto_register.auto_register_unrouted_actions",
        _fake_auto,
    )
    monkeypatch.setattr(
        "src.backend.dsl.commands.setup.register_action_handlers", _explode
    )

    app_factory._configure_auto_registered_actions(MagicMock())

    assert called["auto_called"] is True


# --------------------------------------------------------------------------- #
# _configure_auto_graphql_schema
# --------------------------------------------------------------------------- #


def test_configure_auto_graphql_schema_calls_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_configure_auto_graphql_schema`` зовёт ``auto_register_strawberry_schema``."""
    called: dict[str, Any] = {}

    def _fake_register(app: Any, path: str) -> None:
        called["app"] = app
        called["path"] = path

    monkeypatch.setattr(
        "src.backend.entrypoints.graphql.auto_schema.auto_register_strawberry_schema",
        _fake_register,
    )

    fake_app = MagicMock()
    app_factory._configure_auto_graphql_schema(fake_app)

    assert called["app"] is fake_app
    assert called["path"] == "/api/v1/graphql"


def test_configure_auto_graphql_schema_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_configure_auto_graphql_schema`` не валит startup при ошибке Strawberry."""

    def _explode(*_args: Any, **_kw: Any) -> None:
        raise ImportError("strawberry not installed")

    monkeypatch.setattr(
        "src.backend.entrypoints.graphql.auto_schema.auto_register_strawberry_schema",
        _explode,
    )

    # Не должно бросить.
    app_factory._configure_auto_graphql_schema(MagicMock())


# --------------------------------------------------------------------------- #
# _configure_application_components
# --------------------------------------------------------------------------- #


def test_configure_application_components_calls_middlewares() -> None:
    """``_configure_application_components`` всегда вызывает ``setup_middlewares``."""
    fake_app = MagicMock()
    calls: dict[str, int] = {"middlewares": 0}

    def _fake_middlewares(app: Any) -> None:
        calls["middlewares"] += 1
        assert app is fake_app

    with patch(
        "src.backend.plugins.composition.app_factory.setup_middlewares",
        side_effect=_fake_middlewares,
    ):
        # telemetry/admin/monitoring выключены по дефолту.
        app_factory._configure_application_components(fake_app)

    assert calls["middlewares"] == 1


def test_configure_application_components_tracing_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``setup_tracing`` падает (OTLP коллектор недоступен) — startup не валится."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(settings.app, "telemetry_enabled", True)
    monkeypatch.setattr(settings.app, "admin_enabled", False)
    monkeypatch.setattr(settings.app, "monitoring_enabled", False)

    def _explode_tracing(_: Any) -> None:
        raise ConnectionError("OTLP collector unavailable")

    monkeypatch.setattr(
        "src.backend.plugins.composition.app_factory.setup_tracing", _explode_tracing
    )

    # Не должно бросить.
    app_factory._configure_application_components(MagicMock())


def test_configure_application_components_calls_admin_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``admin_enabled=True`` → ``setup_admin`` вызван."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(settings.app, "telemetry_enabled", False)
    monkeypatch.setattr(settings.app, "admin_enabled", True)
    monkeypatch.setattr(settings.app, "monitoring_enabled", False)

    calls: dict[str, int] = {"admin": 0}

    def _fake_admin(*_args: Any, **_kwargs: Any) -> None:
        calls["admin"] += 1

    monkeypatch.setattr(
        "src.backend.plugins.composition.app_factory.setup_admin", _fake_admin
    )

    app_factory._configure_application_components(MagicMock())
    assert calls["admin"] == 1


def test_configure_application_components_skips_admin_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``admin_enabled=False`` → ``setup_admin`` НЕ вызван."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(settings.app, "telemetry_enabled", False)
    monkeypatch.setattr(settings.app, "admin_enabled", False)
    monkeypatch.setattr(settings.app, "monitoring_enabled", False)

    calls: dict[str, int] = {"admin": 0}

    def _fake_admin(_: Any) -> None:
        calls["admin"] += 1

    monkeypatch.setattr(
        "src.backend.plugins.composition.app_factory.setup_admin", _fake_admin
    )

    app_factory._configure_application_components(MagicMock())
    assert calls["admin"] == 0


def test_configure_application_components_calls_monitoring_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``monitoring_enabled=True`` → ``setup_monitoring`` вызван."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(settings.app, "telemetry_enabled", False)
    monkeypatch.setattr(settings.app, "admin_enabled", False)
    monkeypatch.setattr(settings.app, "monitoring_enabled", True)

    calls: dict[str, int] = {"monitoring": 0}

    def _fake_monitoring(*_args: Any, **_kwargs: Any) -> None:
        calls["monitoring"] += 1

    monkeypatch.setattr(
        "src.backend.plugins.composition.app_factory.setup_monitoring", _fake_monitoring
    )

    app_factory._configure_application_components(MagicMock())
    assert calls["monitoring"] == 1
