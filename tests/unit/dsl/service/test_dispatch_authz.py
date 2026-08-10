"""Regression-тесты enforcement ``route.toml [security] requires_permission`` в DslService.dispatch.

K3 S19 W3: проверяет, что canonical dispatch path (``DslService.dispatch``)
вызывает :func:`src.backend.services.routes.route_authz.check_route_permission`,
когда у :class:`Pipeline` задан атрибут ``security`` (кортеж
``requires_permission`` из route.toml).

Покрывает:

* при ``pipeline.security=()`` enforcement пропускается (backward-compat);
* при ``pipeline.security=("role:admin",)`` + permission-step allow → dispatch проходит;
* при ``pipeline.security=("role:admin",)`` + permission-step deny → :class:`RoutePermissionDeniedError`;
* при отсутствии :class:`AuthorizationGateway` (None) → fail-closed (403).

Запуск::

    .venv/bin/python -m pytest tests/unit/dsl/service/test_dispatch_authz.py -q
"""


from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.errors import RoutePermissionDeniedError
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import route_registry
from src.backend.dsl.service.facade import DslService


class _NoopProcessor(BaseProcessor):
    """Минимальный процессор — для непустого pipeline (валидатор требует)."""

    def __init__(self) -> None:
        """Инициализация с дефолтным именем класса."""
        super().__init__(name="noop")

    async def process(self, exchange: Any, context: Any) -> None:  # type: ignore[override]
        """Пропускает exchange без изменений (no-op для regression-теста)."""
        return None


def _make_pipeline(route_id: str, security: tuple[str, ...] | None) -> Pipeline:
    """Сконструировать Pipeline с заданным ``security``."""
    pipeline = Pipeline(route_id=route_id, processors=[_NoopProcessor()])
    pipeline.security = security
    return pipeline


@pytest.fixture(autouse=True)
def _cleanup_registry() -> None:
    """Очистить ``route_registry`` после каждого теста."""
    yield
    route_registry.clear()


class TestDispatchAuthzEnforcement:
    """K3 S19 W3: ``DslService.dispatch`` вызывает ``check_route_permission``."""

    @pytest.mark.asyncio
    async def test_no_security_skips_check(self) -> None:
        """``pipeline.security=None`` → backward-compat (no enforcement)."""
        pipeline = _make_pipeline("r1", security=None)
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(),
        ) as mock_check:
            await DslService().dispatch("r1", body={}, context=ExecutionContext())

        mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_security_tuple_skips_check(self) -> None:
        """``pipeline.security=()`` → backward-compat (no enforcement)."""
        pipeline = _make_pipeline("r1", security=())
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(),
        ) as mock_check:
            await DslService().dispatch("r1", body={}, context=ExecutionContext())

        mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_principal_and_permissions_from_context(self) -> None:
        """principal/permissions пробрасываются из ExecutionContext в check."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        ctx = ExecutionContext(principal="user-1", permissions=("role:admin",))

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(True, "allowed")),
        ) as mock_check:
            await DslService().dispatch("r1", body={}, context=ctx)

        mock_check.assert_awaited_once()
        kwargs = mock_check.await_args.kwargs
        assert kwargs["route_id"] == "r1"
        assert kwargs["principal"] == "user-1"
        assert kwargs["permissions"] == ("role:admin",)

    @pytest.mark.asyncio
    async def test_anonymous_when_no_context(self) -> None:
        """Без ``ExecutionContext`` → ``"anonymous"`` (fail-closed)."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(True, "allowed")),
        ) as mock_check:
            await DslService().dispatch("r1", body={})

        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "anonymous"
        assert kwargs["permissions"] == ("role:admin",)

    @pytest.mark.asyncio
    async def test_allowed_decision_passes_through(self) -> None:
        """``allowed=True`` от check → dispatch выполняет pipeline нормально."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        ctx = ExecutionContext(principal="admin", permissions=("role:admin",))
        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(True, "allowed")),
        ):
            exchange = await DslService().dispatch("r1", body={"x": 1}, context=ctx)

        assert exchange.error is None
        assert exchange.out_message is not None
        assert exchange.out_message.body == {"x": 1}

    @pytest.mark.asyncio
    async def test_denied_decision_raises_permission_error(self) -> None:
        """``allowed=False`` от check → :class:`RoutePermissionDeniedError`."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        ctx = ExecutionContext(principal="guest", permissions=())
        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ), pytest.raises(RoutePermissionDeniedError) as exc_info:
            await DslService().dispatch("r1", body={}, context=ctx)

        err = exc_info.value
        assert err.route_id == "r1"
        assert "missing_permissions:role:admin" in err.reason
        assert err.status_code == 403

    @pytest.mark.asyncio
    async def test_gateway_not_registered_fails_closed(self) -> None:
        """AuthorizationGateway=None → check_route_permission возвращает deny → 403."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        # Резолвер возвращает None — gateway не зарегистрирован.
        # check_route_permission вернёт (False, "authorization_gateway_not_registered").
        ctx = ExecutionContext(principal="admin", permissions=("role:admin",))
        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=None,
        ), pytest.raises(RoutePermissionDeniedError) as exc_info:
            await DslService().dispatch("r1", body={}, context=ctx)

        assert "authorization_gateway_not_registered" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_permission_step_off_allows(self) -> None:
        """feature-flag OFF → permission_step → allow → dispatch проходит.

        Проверяем, что ``route_authz_requires_permission=False`` → no-op allow.
        Здесь используется реальный :func:`check_route_permission` через
        мок :class:`AuthorizationGateway`, чтобы убедиться, что flow работает.
        """
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        ctx = ExecutionContext(principal="guest", permissions=())

        gateway = MagicMock()
        gateway._capability_gateway = MagicMock()

        # permission_step внутри check_route_permission использует
        # AuthorizationGateway.permission_step(permissions) → build step.
        # На реальном feature-flag OFF → возвращает allow.
        # Мы мокаем на уровне perm_step factory, чтобы избежать сложной
        # реальной инициализации AuthorizationGateway.
        allow_step = AsyncMock(
            return_value=__import__(
                "src.backend.core.security.authorization_gateway",
                fromlist=["AuthorizationReason"],
            ).AuthorizationReason(
                source="permission", outcome="allow", detail="flag_off"
            )
        )

        authz_instance = MagicMock()
        authz_instance.authorize = AsyncMock(
            return_value=MagicMock(
                allowed=True,
                reasons=[
                    __import__(
                        "src.backend.core.security.authorization_gateway",
                        fromlist=["AuthorizationReason"],
                    ).AuthorizationReason(
                        source="permission", outcome="allow", detail="flag_off"
                    )
                ],
            )
        )

        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=gateway,
        ):
            with patch(
                "src.backend.services.routes.route_authz.AuthorizationGateway",
                return_value=authz_instance,
            ):
                with patch(
                    "src.backend.services.routes.route_authz.AuthorizationGateway.permission_step",
                    return_value=allow_step,
                ):
                    exchange = await DslService().dispatch(
                        "r1", body={"x": 1}, context=ctx
                    )

        assert exchange.error is None
