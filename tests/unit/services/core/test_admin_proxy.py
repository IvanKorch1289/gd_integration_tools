"""TDD characterization для services/core/admin.py lazy proxy (Sprint 225 Tier 3)."""

from __future__ import annotations

import pytest


class TestAdminDSLExportsIdentity:
    """action_handler_registry + route_registry identity preserved."""

    def test_action_handler_registry_identity(self) -> None:
        from src.backend.services.core.admin import action_handler_registry
        from src.backend.dsl.commands.action_registry import (
            action_handler_registry as _orig,
        )

        assert action_handler_registry is _orig

    def test_route_registry_identity(self) -> None:
        from src.backend.services.core.admin import route_registry
        from src.backend.dsl.commands.registry import route_registry as _orig

        assert route_registry is _orig


class TestAdminServiceClass:
    """AdminService class still works after refactor."""

    def test_admin_service_class_exists(self) -> None:
        from src.backend.services.core.admin import AdminService

        assert AdminService is not None

    def test_get_admin_service_callable(self) -> None:
        from src.backend.services.core.admin import get_admin_service

        assert callable(get_admin_service)


class TestAdminUnknownAttribute:
    """Unknown attribute raises AttributeError."""

    def test_unknown_raises(self) -> None:
        from src.backend.services.core import admin

        with pytest.raises(AttributeError):
            _ = admin.__getattr__("nonexistent_xyz")
