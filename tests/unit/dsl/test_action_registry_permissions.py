"""ADR-0421 — enforcement прав на action-поверхности (``ActionHandlerRegistry``).

До ADR-0421 поле ``ActionMetadata.permissions`` только пропагировалось и
нигде не проверялось: ``dispatch()`` валидировал лишь payload. Любой
аутентифицированный пользователь мог вызвать admin-action
(``admin.get_config`` → ``settings.model_dump()``) через auto-/invocation-
поверхность.

Тесты покрывают:

* отказ по ``ActionMetadata.permissions`` (fail-closed, HTTP 403);
* отказ для action'ов с ``admin``-префиксом (требуется ``role:admin``);
* отсутствие прав у обычных action'ов (backward compat);
* audit-событие ``action.permission_denied`` при отказе;
* сборку эффективных permissions из ``AuthContext`` (user-permissions +
  admin-роли).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.interfaces.action_dispatcher import ActionMetadata
from src.backend.core.types.invocation_command import (
    ActionCommandMetaSchema,
    ActionCommandSchema,
)
from src.backend.dsl.commands.action_registry import (
    ADMIN_PERMISSION,
    ActionHandlerRegistry,
    ActionHandlerSpec,
    ActionPermissionDeniedError,
    enforce_action_permissions,
    required_action_permissions,
    resolve_action_permissions,
)


class _EchoService:
    """Сервис-заглушка: единственный метод ``run``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"ok": True}


def _command(
    action: str, *, principal: str = "", permissions: tuple[str, ...] = ()
) -> ActionCommandSchema:
    """Собирает команду с principal/permissions в meta."""
    return ActionCommandSchema(
        action=action,
        payload={},
        meta=ActionCommandMetaSchema(
            principal=principal, permissions=list(permissions)
        ),
    )


@pytest.fixture(autouse=True)
def _no_audit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отключает реальный ClickHouse-audit в тестах (нет сетевых вызовов)."""
    audit_service = AsyncMock()
    monkeypatch.setattr(
        "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
        lambda: audit_service,
    )


class TestRequiredActionPermissions:
    """Вычисление требуемых permissions."""

    def test_metadata_permissions_win(self) -> None:
        metadata = ActionMetadata(
            action="orders.get", permissions=("scope:orders.read",)
        )
        assert required_action_permissions("orders.get", metadata) == (
            "scope:orders.read",
        )

    def test_admin_prefix_requires_role_admin(self) -> None:
        assert required_action_permissions("admin.get_config", None) == (
            ADMIN_PERMISSION,
        )
        assert required_action_permissions("admin_get_config", None) == (
            ADMIN_PERMISSION,
        )

    def test_metadata_wins_over_admin_prefix(self) -> None:
        metadata = ActionMetadata(
            action="admin.get_config", permissions=("scope:config.read",)
        )
        assert required_action_permissions("admin.get_config", metadata) == (
            "scope:config.read",
        )

    def test_plain_action_requires_nothing(self) -> None:
        assert required_action_permissions("orders.get", None) == ()


class TestDispatchPermissionEnforcement:
    """``dispatch()`` обязан проверять права (fail-closed)."""

    async def test_denied_when_metadata_permission_missing(self) -> None:
        registry = ActionHandlerRegistry()
        service = _EchoService()
        registry.register_with_metadata(
            action="orders.get",
            handler=ActionHandlerSpec(
                action="orders.get",
                service_getter=lambda: service,
                service_method="run",
            ),
            metadata=ActionMetadata(
                action="orders.get", permissions=("scope:orders.read",)
            ),
        )

        with pytest.raises(ActionPermissionDeniedError) as exc:
            await registry.dispatch(_command("orders.get", principal="u-1"))

        assert exc.value.status_code == 403
        assert exc.value.missing == ("scope:orders.read",)
        assert service.calls == []

    async def test_allowed_when_permission_granted(self) -> None:
        registry = ActionHandlerRegistry()
        service = _EchoService()
        registry.register_with_metadata(
            action="orders.get",
            handler=ActionHandlerSpec(
                action="orders.get",
                service_getter=lambda: service,
                service_method="run",
            ),
            metadata=ActionMetadata(
                action="orders.get", permissions=("scope:orders.read",)
            ),
        )

        result = await registry.dispatch(
            _command("orders.get", principal="u-1", permissions=("scope:orders.read",))
        )

        assert result == {"ok": True}
        assert service.calls == [{}]

    async def test_admin_prefix_denied_without_role_admin(self) -> None:
        registry = ActionHandlerRegistry()
        service = _EchoService()
        registry.register(
            action="admin.get_config",
            service_getter=lambda: service,
            service_method="run",
        )

        with pytest.raises(ActionPermissionDeniedError) as exc:
            await registry.dispatch(_command("admin.get_config", principal="u-1"))

        assert exc.value.status_code == 403
        assert exc.value.required == (ADMIN_PERMISSION,)
        assert service.calls == []

    async def test_admin_prefix_allowed_with_role_admin(self) -> None:
        registry = ActionHandlerRegistry()
        service = _EchoService()
        registry.register(
            action="admin.get_config",
            service_getter=lambda: service,
            service_method="run",
        )

        result = await registry.dispatch(
            _command(
                "admin.get_config",
                principal="admin:alice",
                permissions=(ADMIN_PERMISSION,),
            )
        )

        assert result == {"ok": True}
        assert service.calls == [{}]

    async def test_action_without_permissions_still_works(self) -> None:
        """Backward compat: обычные action'ы не требуют прав."""
        registry = ActionHandlerRegistry()
        service = _EchoService()
        registry.register(
            action="orders.get", service_getter=lambda: service, service_method="run"
        )

        result = await registry.dispatch(_command("orders.get"))

        assert result == {"ok": True}

    async def test_denial_emits_audit_event(self) -> None:
        registry = ActionHandlerRegistry()
        registry.register(
            action="admin.get_config",
            service_getter=lambda: _EchoService(),
            service_method="run",
        )
        audit = AsyncMock()
        audit_service = AsyncMock()
        audit_service.emit = audit

        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            return_value=audit_service,
        ):
            with pytest.raises(ActionPermissionDeniedError):
                await registry.dispatch(_command("admin.get_config", principal="u-1"))

        audit.assert_awaited_once()
        kwargs = audit.await_args.kwargs
        assert kwargs["event"] == "action.permission_denied"
        assert kwargs["outcome"] == "denied"
        assert kwargs["resource"] == "action/admin.get_config"

    def test_required_permissions_lookup(self) -> None:
        registry = ActionHandlerRegistry()
        registry.register(
            action="admin.invalidate_cache",
            service_getter=lambda: _EchoService(),
            service_method="run",
        )

        assert registry.required_permissions("admin.invalidate_cache") == (
            ADMIN_PERMISSION,
        )
        assert (
            registry.missing_permissions("admin.invalidate_cache", (ADMIN_PERMISSION,))
            == ()
        )
        assert registry.missing_permissions("admin.invalidate_cache", ()) == (
            ADMIN_PERMISSION,
        )


class TestResolveActionPermissions:
    """Сборка эффективных permissions из ``AuthContext``."""

    def test_none_auth_yields_empty(self) -> None:
        assert resolve_action_permissions(None) == ()

    def test_user_permissions_preserved(self) -> None:
        auth = AuthContext(
            method=AuthMethod.JWT,
            principal="u-1",
            metadata={"permissions": ["scope:orders.read"]},
        )
        assert resolve_action_permissions(auth) == ("scope:orders.read",)

    def test_admin_role_grants_role_admin(self) -> None:
        auth = AuthContext(
            method=AuthMethod.JWT,
            principal="admin:alice",
            metadata={"admin_roles": ["super_admin"]},
        )
        assert ADMIN_PERMISSION in resolve_action_permissions(auth)

    def test_admin_role_and_user_permissions_merged(self) -> None:
        auth = AuthContext(
            method=AuthMethod.JWT,
            principal="admin:alice",
            metadata={
                "permissions": ["scope:orders.read"],
                "admin_roles": ["operator"],
            },
        )
        permissions = resolve_action_permissions(auth)
        assert "scope:orders.read" in permissions
        assert ADMIN_PERMISSION in permissions


class TestEnforceActionPermissions:
    """Прямой вызов канонической проверки прав."""

    async def test_empty_required_allows(self) -> None:
        await enforce_action_permissions(action="orders.get", required=(), granted=())

    async def test_missing_permission_raises(self) -> None:
        with pytest.raises(ActionPermissionDeniedError) as exc:
            await enforce_action_permissions(
                action="orders.get",
                required=("scope:orders.read",),
                granted=(),
                principal="u-1",
            )
        assert exc.value.action == "orders.get"
        assert exc.value.to_detail() == {
            "code": "action_permission_denied",
            "action": "orders.get",
            "required": ["scope:orders.read"],
        }

    async def test_all_permissions_required(self) -> None:
        """Семантика AND (как в ``permission_step``)."""
        with pytest.raises(ActionPermissionDeniedError):
            await enforce_action_permissions(
                action="orders.get",
                required=("scope:a", "scope:b"),
                granted=("scope:a",),
            )
