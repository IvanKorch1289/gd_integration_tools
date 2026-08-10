"""Регресс-тесты: ``AuthorizationGateway`` зарегистрирован в composition root (Sprint 1 K5).

Sprint 1 K5: ``AuthorizationGateway`` singleton должен быть доступен через
``app.state.authorization_gateway`` после :func:`register_app_state`, а
lazy resolver :func:`src.backend.core.security.authorization_gateway.get_authorization_gateway`
должен возвращать его без ``Request``.

Pre-state (зафиксировано до Sprint 1.2):

* :class:`AuthorizationGateway` НЕ регистрировался в composition root
  → ``app.state.authorization_gateway`` всегда отсутствовал
  → :meth:`PolicyMixin._resolve_authz_gateway` всегда возвращал ``None``
  → LLM policy-gate работал только в fail-closed режиме.
* В ``plugins/composition/di.py::register_app_state`` не было соответствующей
  инициализации.
* ``get_authorization_gateway`` отсутствовал как в ``composition/di.py``
  (Depends), так и в ``core/security/authorization_gateway/__init__.py``
  (lazy resolver).

Тесты:

1. :func:`register_app_state` пишет ``app.state.authorization_gateway``.
2. :func:`di.get_authorization_gateway` (FastAPI Depends) возвращает его.
3. Lazy resolver :func:`core.security.authorization_gateway.get_authorization_gateway`
   работает в non-request контексте.
4. :class:`AuthorizationGateway` через резолвер успешно выполняет
   ``authorize(...)`` для разрешённого principal (smoke).
5. Существующие ``test_route_authz`` и ``test_dispatch_authz`` контракты не
   сломаны (см. ``TestBackwardCompatRouteAuthz`` ниже).
"""


from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from src.backend.plugins.composition import di

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def fresh_app() -> FastAPI:
    """Свежий FastAPI app с минимальным state."""
    return FastAPI()


@pytest.fixture
def stub_constructors(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Подменяет ВСЕ тяжёлые конструкторы из ``register_app_state`` лёгкими mock'ами.

    ВАЖНО: ``AuthorizationGateway`` НЕ подменяется — мы хотим проверить,
    что composition root создаёт РЕАЛЬНЫЙ инстанс и кладёт его в state.
    """
    instances: dict[str, MagicMock] = {}

    def _make_stub(attr: str) -> MagicMock:
        mock = MagicMock(name=attr)
        instances[attr] = mock
        return mock

    monkeypatch.setattr(
        "src.backend.infrastructure.security.api_key_manager.APIKeyManager",
        lambda: _make_stub("api_key_manager"),
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.tracer.ExecutionTracer", lambda: _make_stub("tracer"),
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
    monkeypatch.setattr(
        "src.backend.entrypoints.mqtt.mqtt_handler.MqttHandler",
        lambda settings: _make_stub("mqtt_handler"),
    )
    reply_reg = _make_stub("reply_registry")
    monkeypatch.setattr(
        "src.backend.infrastructure.messaging.invocation_replies.get_reply_channel_registry",
        lambda: reply_reg,
    )
    monkeypatch.setattr(
        "src.backend.services.execution.invoker.Invoker", lambda: _make_stub("invoker"),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.watermark.factory.create_watermark_store",
        lambda *args, **kwargs: _make_stub("watermark_store"),
    )
    return instances


# --------------------------------------------------------------------------- #
# Module surface (post-state)
# --------------------------------------------------------------------------- #


def test_di_module_all_contains_get_authorization_gateway() -> None:
    """``get_authorization_gateway`` обязательно экспортируется из ``di``."""
    assert "get_authorization_gateway" in di.__all__


def test_get_authorization_gateway_is_coroutine() -> None:
    """``di.get_authorization_gateway`` — async (FastAPI Depends)."""
    import asyncio

    assert asyncio.iscoroutinefunction(di.get_authorization_gateway)


def test_lazy_resolver_exported_from_authorization_gateway_package() -> None:
    """``get_authorization_gateway`` доступен как public symbol пакета."""
    from src.backend.core.security.authorization_gateway import (
        get_authorization_gateway,
    )

    assert callable(get_authorization_gateway)


# --------------------------------------------------------------------------- #
# register_app_state — пишет authorization_gateway в state
# --------------------------------------------------------------------------- #


def test_register_app_state_writes_authorization_gateway(
    fresh_app: FastAPI, stub_constructors: dict[str, MagicMock],
) -> None:
    """После ``register_app_state`` ``app.state.authorization_gateway`` существует."""
    di.register_app_state(fresh_app)

    assert hasattr(fresh_app.state, "authorization_gateway")
    assert fresh_app.state.authorization_gateway is not None


def test_register_app_state_authorization_gateway_is_real_instance(
    fresh_app: FastAPI, stub_constructors: dict[str, MagicMock],
) -> None:
    """``app.state.authorization_gateway`` — настоящий ``AuthorizationGateway``."""
    from src.backend.core.security.authorization_gateway import AuthorizationGateway

    di.register_app_state(fresh_app)

    assert isinstance(fresh_app.state.authorization_gateway, AuthorizationGateway)


def test_register_app_state_authorization_gateway_has_capability_adapter(
    fresh_app: FastAPI, stub_constructors: dict[str, MagicMock],
) -> None:
    """Gateway сконструирован с ``FacadeCapabilityAdapter`` (per S198 pattern)."""
    from src.backend.services.admin._capability_adapter import FacadeCapabilityAdapter

    di.register_app_state(fresh_app)

    cap_gw = fresh_app.state.authorization_gateway._capability_gateway
    assert isinstance(cap_gw, FacadeCapabilityAdapter)


def test_register_app_state_is_idempotent_with_authorization_gateway(
    fresh_app: FastAPI, stub_constructors: dict[str, MagicMock],
) -> None:
    """Повторный ``register_app_state`` (после ``reset_app_state``) переписывает gateway."""
    from src.backend.core.di.app_state import reset_app_state

    di.register_app_state(fresh_app)
    first = fresh_app.state.authorization_gateway

    reset_app_state()
    di.register_app_state(fresh_app)
    second = fresh_app.state.authorization_gateway

    assert first is not None
    assert second is not None
    # Разные инстансы — каждый ``register_app_state`` создаёт свежий gateway.
    assert first is not second


# --------------------------------------------------------------------------- #
# FastAPI Depends — get_authorization_gateway(request)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_authorization_gateway_depends_returns_state_value(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """``di.get_authorization_gateway(request)`` возвращает gateway из state."""
    app = FastAPI()
    di.register_app_state(app)

    request = Request(
        scope={"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"},
    )
    result = await di.get_authorization_gateway(request)

    assert result is app.state.authorization_gateway


@pytest.mark.asyncio
async def test_get_authorization_gateway_depends_raises_when_unregistered(
    fresh_app: FastAPI,
) -> None:
    """Если ``register_app_state`` не вызывался → ``AttributeError`` (fail-loud).

    Согласуется с другими ``get_xxx(request)`` Depends-функциями — они
    полагаются на ``register_app_state``, и при отсутствии атрибута
    поднимается AttributeError, не RuntimeError.
    """
    request = Request(
        scope={
            "type": "http",
            "app": fresh_app,
            "headers": [],
            "path": "/",
            "method": "GET",
        },
    )
    with pytest.raises(AttributeError):
        await di.get_authorization_gateway(request)


# --------------------------------------------------------------------------- #
# Lazy resolver — non-FastAPI контекст
# --------------------------------------------------------------------------- #


def test_lazy_resolver_returns_registered_instance(
    stub_constructors: dict[str, MagicMock],
) -> None:
    """После ``register_app_state`` lazy resolver возвращает реальный gateway."""
    from src.backend.core.security.authorization_gateway import (
        get_authorization_gateway,
    )

    app = FastAPI()
    di.register_app_state(app)

    result = get_authorization_gateway()

    assert result is app.state.authorization_gateway


def test_lazy_resolver_returns_none_when_app_not_registered() -> None:
    """Без ``register_app_state`` (``get_app_ref() is None``) → ``None``."""
    from src.backend.core.di.app_state import reset_app_state
    from src.backend.core.security.authorization_gateway import (
        get_authorization_gateway,
    )

    reset_app_state()

    result = get_authorization_gateway()

    assert result is None


def test_lazy_resolver_returns_none_when_state_attr_missing() -> None:
    """Если app зарегистрирован, но ``authorization_gateway`` отсутствует → ``None``."""
    from fastapi import FastAPI

    from src.backend.core.di.app_state import reset_app_state, set_app_ref
    from src.backend.core.security.authorization_gateway import (
        get_authorization_gateway,
    )

    reset_app_state()
    set_app_ref(FastAPI(), allow_replace=True)

    result = get_authorization_gateway()

    assert result is None


def test_lazy_resolver_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если резолв падает (например, app.state не существует) → ``None``, не raise."""
    from src.backend.core.di import app_state as app_state_module
    from src.backend.core.security.authorization_gateway import (
        get_authorization_gateway,
    )

    def _explode() -> Any:
        raise RuntimeError("simulated app.state lookup failure")

    monkeypatch.setattr(app_state_module, "get_app_ref", _explode)

    # Не должно бросить исключение наружу.
    result = get_authorization_gateway()
    assert result is None


# --------------------------------------------------------------------------- #
# Smoke: gateway через резолвер выполняет authorize()
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolved_gateway_authorize_returns_decision(
    stub_constructors: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lazy-резолвнутый gateway может выполнить ``authorize(...)`` без ошибок.

    Подменяем :class:`CapabilityGatewayProtocol`-совместимый gate на mock,
    чтобы не зависеть от реальной capability-конфигурации.
    """
    from src.backend.core.security.authorization_gateway import (
        get_authorization_gateway,
    )

    cap_mock = MagicMock()
    cap_mock.check = MagicMock(return_value=None)  # не raise = allow

    monkeypatch.setattr(
        "src.backend.services.admin._capability_adapter.FacadeCapabilityAdapter.__init__",
        lambda self, facade: setattr(self, "_facade", cap_mock),
    )

    app = FastAPI()
    di.register_app_state(app)

    gateway = get_authorization_gateway()
    assert gateway is not None

    # Дёргаем без feature-flag (default OFF → внутренний _is_enabled вернёт False → allow).
    decision = await gateway.authorize(
        principal="test-principal", resource="test:resource", action="read",
    )

    assert decision.allowed is True


# --------------------------------------------------------------------------- #
# Backward-compat: существующие test_route_authz / test_dispatch_authz контракты
# --------------------------------------------------------------------------- #


class TestBackwardCompatRouteAuthz:
    """Patches ``_resolve_authz_gateway`` в ``route_authz.py`` продолжают работать.

    Sprint 1.2 НЕ модифицирует ``services/routes/route_authz.py::_resolve_authz_gateway``
    — он по-прежнему читает ``agent._authz_gateway``. Существующие тесты
    патчат эту private-функцию через ``unittest.mock.patch`` и должны
    продолжать работать как раньше.
    """

    @pytest.mark.asyncio
    async def test_route_authz_patch_returns_none(self) -> None:
        """Патч ``_resolve_authz_gateway`` возвращает ``None`` — check возвращает deny."""
        from src.backend.services.routes.route_authz import check_route_permission

        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=None,
        ):
            allowed, reason = await check_route_permission(
                route_id="r1", principal="user-1", permissions=("role:admin",),
            )

        assert allowed is False
        assert "authorization_gateway_not_registered" in reason

    @pytest.mark.asyncio
    async def test_dispatch_authz_with_patch(self) -> None:
        """``DslService.dispatch`` корректно обрабатывает патчнутый gateway=None."""
        from src.backend.core.errors import RoutePermissionDeniedError
        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.pipeline import Pipeline
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.registry import route_registry
        from src.backend.dsl.service.facade import DslService

        class _NoopProcessor(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="noop")

            async def process(self, exchange: Any, context: Any) -> None:
                return None

        pipeline = Pipeline(route_id="r1", processors=[_NoopProcessor()])
        pipeline.security = ("role:admin",)
        route_registry.register(pipeline)

        try:
            with patch(
                "src.backend.services.routes.route_authz._resolve_authz_gateway",
                return_value=None,
            ), pytest.raises(RoutePermissionDeniedError) as exc_info:
                await DslService().dispatch(
                    "r1",
                    body={},
                    context=ExecutionContext(principal="admin", permissions=()),
                )
            assert "authorization_gateway_not_registered" in exc_info.value.reason
        finally:
            route_registry.clear()


# --------------------------------------------------------------------------- #
# Module-level: composition root wiring прошёл через FacadeCapabilityAdapter
# --------------------------------------------------------------------------- #


def test_authorization_gateway_uses_capability_facade_singleton(
    stub_constructors: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Composition root использует существующий ``get_capability_facade()`` singleton.

    Подтверждаем через patching ``get_capability_facade``: после ``register_app_state``
    adapter внутри gateway должен быть сконструирован именно с тем facade,
    что вернул ``get_capability_facade()``.
    """
    sentinel = MagicMock(name="capability_facade_sentinel")
    monkeypatch.setattr(
        "src.backend.services.capabilities.facade.get_capability_facade",
        lambda: sentinel,
    )

    app = FastAPI()
    di.register_app_state(app)

    cap_gw = app.state.authorization_gateway._capability_gateway
    assert cap_gw._facade is sentinel
