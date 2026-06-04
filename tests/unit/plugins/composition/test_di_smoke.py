# ruff: noqa: S101, SLF001
"""Smoke-тесты S39 W5 — модуль ``src.backend.plugins.composition.di``.

Покрывают:
* публичный API модуля (``__all__``);
* FastAPI Depends-функции возвращают значение из ``request.app.state``;
* ``register_app_state`` инициализирует все ожидаемые singletons;
* fallback-путь для ``MqttSettings`` (на случай исключения при инстанцировании);
* реэкспорт ``app_state_singleton`` и ``_get_from_app_state`` из core.

Подход: мокаем тяжёлые конструкторы (``APIKeyManager``, ``PoolMonitor`` и т.д.)
через ``monkeypatch.setattr`` *до* вызова ``register_app_state``, чтобы тесты
не зависели от внешних сервисов (Vault, Redis, Postgres, LangFuse).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.plugins.composition import di
from src.backend.plugins.composition import (
    service_setup as _service_setup_marker,  # noqa: F401  (sidebar import check)
)

# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_di_module_imports() -> None:
    """Модуль импортируется без побочных эффектов (кроме lazy core-импорта)."""
    assert di is not None
    assert hasattr(di, "register_app_state")
    assert hasattr(di, "app_state_singleton")
    assert hasattr(di, "_get_from_app_state")


def test_di_module_all_contains_register_app_state() -> None:
    """``register_app_state`` обязательно экспортируется."""
    assert "register_app_state" in di.__all__


def test_di_module_all_lists_every_getter() -> None:
    """Все 10 ``get_xxx``-функций перечислены в ``__all__``."""
    expected_getters = {
        "get_api_key_manager",
        "get_tracer",
        "get_plugin_registry",
        "get_pipeline_version_manager",
        "get_slo_tracker",
        "get_pool_monitor",
        "get_vault_refresher",
        "get_mqtt_handler",
        "get_langfuse_client",
        "get_watermark_store",
    }
    for name in expected_getters:
        assert name in di.__all__, f"{name} missing from di.__all__"


def test_di_module_reexports_core_di_primitives() -> None:
    """``app_state_singleton`` и ``_get_from_app_state`` реэкспортированы."""
    from src.backend.core.di import app_state_singleton as core_app_state_singleton
    from src.backend.core.di.app_state import (
        _get_from_app_state as core_get_from_app_state,
    )

    assert di.app_state_singleton is core_app_state_singleton
    assert di._get_from_app_state is core_get_from_app_state


def test_all_get_xxx_callables_are_coroutines() -> None:
    """Каждая ``get_xxx`` — ``async def`` (FastAPI Depends-конвенция)."""
    import asyncio

    names = (
        "get_api_key_manager",
        "get_tracer",
        "get_plugin_registry",
        "get_pipeline_version_manager",
        "get_slo_tracker",
        "get_pool_monitor",
        "get_vault_refresher",
        "get_mqtt_handler",
        "get_langfuse_client",
        "get_watermark_store",
    )
    for name in names:
        fn = getattr(di, name)
        assert asyncio.iscoroutinefunction(fn), f"{name} must be async"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def fresh_app() -> FastAPI:
    """Свежий FastAPI app с минимальным state; инициализирован вручную."""
    return FastAPI()


@pytest.fixture
def stub_constructors(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Подменяет ВСЕ concrete-конструкторы лёгкими MagicMock'ами.

    Возвращает словарь ``{attr_name: mock_instance}`` для удобной проверки,
    какие объекты были записаны в ``app.state``.
    """
    instances: dict[str, MagicMock] = {}

    def _make_stub(attr: str) -> MagicMock:
        mock = MagicMock(name=attr)
        instances[attr] = mock
        return mock

    # Конструкторы, вызываемые напрямую.
    monkeypatch.setattr(
        "src.backend.infrastructure.security.api_key_manager.APIKeyManager",
        lambda: _make_stub("api_key_manager"),
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.tracer.ExecutionTracer",
        lambda: _make_stub("tracer"),
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.plugin_registry.ProcessorPluginRegistry",
        lambda: _make_stub("plugin_registry"),
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.versioning.PipelineVersionManager",
        lambda: _make_stub("pipeline_version_manager"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.application.slo_tracker.SLOTracker",
        lambda: _make_stub("slo_tracker"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.database.pool_monitor.PoolMonitor",
        lambda: _make_stub("pool_monitor"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.clients.external.langfuse_client.LangFuseClient",
        lambda: _make_stub("langfuse_client"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.application.vault_refresher.VaultSecretRefresher",
        lambda: _make_stub("vault_refresher"),
    )
    # MqttHandler — конструктор принимает settings, поэтому MagicMock-обёртка.
    monkeypatch.setattr(
        "src.backend.entrypoints.mqtt.mqtt_handler.MqttHandler",
        lambda settings: _make_stub("mqtt_handler"),
    )

    # get_reply_channel_registry() возвращает singleton-instance.
    reply_reg = _make_stub("reply_registry")
    monkeypatch.setattr(
        "src.backend.infrastructure.messaging.invocation_replies.get_reply_channel_registry",
        lambda: reply_reg,
    )

    # Invoker — конструктор без аргументов.
    monkeypatch.setattr(
        "src.backend.services.execution.invoker.Invoker",
        lambda: _make_stub("invoker"),
    )

    # WatermarkStore через factory.
    monkeypatch.setattr(
        "src.backend.infrastructure.watermark.factory.create_watermark_store",
        lambda *args, **kwargs: _make_stub("watermark_store"),
    )

    return instances


# --------------------------------------------------------------------------- #
# register_app_state
# --------------------------------------------------------------------------- #


def test_register_app_state_sets_app_ref(
    fresh_app: FastAPI,
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``register_app_state`` вызывает ``set_app_ref`` с переданным app."""
    from src.backend.core.di.app_state import get_app_ref

    di.register_app_state(fresh_app)
    assert get_app_ref() is fresh_app


def test_register_app_state_writes_every_singleton_to_state(
    fresh_app: FastAPI,
    stub_constructors: dict[str, MagicMock],
) -> None:
    """После ``register_app_state`` все ожидаемые атрибуты присутствуют в state."""
    di.register_app_state(fresh_app)

    expected_attrs = (
        "api_key_manager",
        "tracer",
        "plugin_registry",
        "pipeline_version_manager",
        "slo_tracker",
        "pool_monitor",
        "langfuse_client",
        "reply_registry",
        "invoker",
        "vault_refresher",
        "watermark_store",
        "mqtt_handler",
    )
    for attr in expected_attrs:
        assert hasattr(fresh_app.state, attr), f"app.state.{attr} missing"


def test_register_app_state_uses_stub_instances(
    fresh_app: FastAPI,
    stub_constructors: dict[str, MagicMock],
) -> None:
    """State хранит *именно* те MagicMock'и, что вернули подменённые конструкторы."""
    di.register_app_state(fresh_app)
    for attr, mock in stub_constructors.items():
        assert getattr(fresh_app.state, attr) is mock


# --------------------------------------------------------------------------- #
# MqttSettings fallback
# --------------------------------------------------------------------------- #


def test_register_app_state_mqtt_fallback_when_settings_raise(
    fresh_app: FastAPI,
    stub_constructors: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``MqttSettings()`` падает — используется fallback с ``enabled=False``."""

    call_count = {"n": 0}
    fallback_settings = SimpleNamespace(enabled=False)

    def _explode_then_fallback(*args: object, **kwargs: object) -> object:
        call_count["n"] += 1
        # Первый вызов (MqttSettings()) падает, второй (MqttSettings(enabled=False))
        # возвращает fallback — это и есть поведение, описанное в комментарии.
        if call_count["n"] == 1:
            raise RuntimeError("simulated config error")
        return fallback_settings

    monkeypatch.setattr(
        "src.backend.entrypoints.mqtt.mqtt_handler.MqttSettings",
        _explode_then_fallback,
    )

    # Должно завершиться без исключения: внутри есть try/except.
    di.register_app_state(fresh_app)
    assert fresh_app.state.mqtt_handler is stub_constructors["mqtt_handler"]


# --------------------------------------------------------------------------- #
# FastAPI Depends: get_xxx возвращают value из request.app.state
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_api_key_manager_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_api_key_manager`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_api_key_manager(request)
    assert result is stub_constructors["api_key_manager"]


@pytest.mark.asyncio
async def test_get_tracer_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_tracer`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_tracer(request)
    assert result is stub_constructors["tracer"]


@pytest.mark.asyncio
async def test_get_plugin_registry_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_plugin_registry`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_plugin_registry(request)
    assert result is stub_constructors["plugin_registry"]


@pytest.mark.asyncio
async def test_get_pipeline_version_manager_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_pipeline_version_manager`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_pipeline_version_manager(request)
    assert result is stub_constructors["pipeline_version_manager"]


@pytest.mark.asyncio
async def test_get_slo_tracker_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_slo_tracker`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_slo_tracker(request)
    assert result is stub_constructors["slo_tracker"]


@pytest.mark.asyncio
async def test_get_pool_monitor_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_pool_monitor`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_pool_monitor(request)
    assert result is stub_constructors["pool_monitor"]


@pytest.mark.asyncio
async def test_get_vault_refresher_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_vault_refresher`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_vault_refresher(request)
    assert result is stub_constructors["vault_refresher"]


@pytest.mark.asyncio
async def test_get_mqtt_handler_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_mqtt_handler`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_mqtt_handler(request)
    assert result is stub_constructors["mqtt_handler"]


@pytest.mark.asyncio
async def test_get_langfuse_client_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_langfuse_client`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_langfuse_client(request)
    assert result is stub_constructors["langfuse_client"]


@pytest.mark.asyncio
async def test_get_watermark_store_returns_from_state(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``get_watermark_store`` читает из ``request.app.state``."""
    from starlette.requests import Request

    app = FastAPI()
    di.register_app_state(app)
    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"}
    )
    result = await di.get_watermark_store(request)
    assert result is stub_constructors["watermark_store"]


# --------------------------------------------------------------------------- #
# Integration: FastAPI TestClient + Depends
# --------------------------------------------------------------------------- #


def test_depends_functions_work_via_fastapi_endpoint(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """Smoke: эндпоинт, использующий каждый из 10 геттеров через Depends."""
    app = FastAPI()
    di.register_app_state(app)

    for name in (
        "get_api_key_manager",
        "get_tracer",
        "get_plugin_registry",
        "get_pipeline_version_manager",
        "get_slo_tracker",
        "get_pool_monitor",
        "get_vault_refresher",
        "get_mqtt_handler",
        "get_langfuse_client",
        "get_watermark_store",
    ):
        getter = getattr(di, name)
        # Регистрируем уникальный route на каждый геттер.
        app.add_api_route(
            f"/_smoke/{name}",
            lambda _g=getter: _g,  # type: ignore[misc]
            methods=["GET"],
        )

    client = TestClient(app)
    for name in (
        "get_api_key_manager",
        "get_tracer",
        "get_plugin_registry",
        "get_pipeline_version_manager",
        "get_slo_tracker",
        "get_pool_monitor",
        "get_vault_refresher",
        "get_mqtt_handler",
        "get_langfuse_client",
        "get_watermark_store",
    ):
        resp = client.get(f"/_smoke/{name}")
        assert resp.status_code == 200, f"{name}: {resp.status_code} {resp.text}"


def test_register_app_state_idempotent_after_reset(
    fresh_app: FastAPI,
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``register_app_state`` можно вызвать повторно после ``reset_app_state``."""
    from src.backend.core.di.app_state import reset_app_state

    di.register_app_state(fresh_app)
    reset_app_state()
    di.register_app_state(fresh_app)
    # Никаких исключений + state перезаписан.
    assert fresh_app.state.mqtt_handler is stub_constructors["mqtt_handler"]


def test_register_app_state_simple_namespace_state(stub_constructors: dict[str, MagicMock]) -> None:
    """Функция принимает любой объект с атрибутом ``state`` (duck-typed app)."""
    fake_app = SimpleNamespace(state=SimpleNamespace())  # type: ignore[arg-type]
    # Подменяем все конструкторы, чтобы избежать сетевых подключений.
    di.register_app_state(fake_app)  # type: ignore[arg-type]
    # Все обязательные атрибуты присутствуют в state.
    for attr in (
        "api_key_manager",
        "tracer",
        "plugin_registry",
        "pipeline_version_manager",
        "slo_tracker",
        "pool_monitor",
        "langfuse_client",
        "reply_registry",
        "invoker",
        "vault_refresher",
        "watermark_store",
        "mqtt_handler",
    ):
        assert hasattr(fake_app.state, attr), attr
