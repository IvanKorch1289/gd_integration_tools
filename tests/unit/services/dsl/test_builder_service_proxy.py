"""TDD characterization для services/dsl/builder_service.py lazy proxy (Sprint 225 Tier 3)."""

from __future__ import annotations

import pytest


class TestBuilderServiceDSLExportsIdentity:
    """route_registry + YAMLStore identity preserved via lazy __getattr__."""

    def test_route_registry_identity(self) -> None:
        from src.backend.services.dsl.builder_service import route_registry
        from src.backend.dsl.commands.registry import route_registry as _orig

        assert route_registry is _orig

    def test_yaml_store_class_identity(self) -> None:
        from src.backend.services.dsl.builder_service import YAMLStore
        from src.backend.dsl.yaml_store import YAMLStore as _orig

        assert YAMLStore is _orig


class TestBuilderServiceClass:
    """DSLBuilderService class still works after refactor."""

    def test_dsl_builder_service_class_exists(self) -> None:
        from src.backend.services.dsl.builder_service import DSLBuilderService

        assert DSLBuilderService is not None

    def test_get_dsl_builder_service_callable(self) -> None:
        from src.backend.services.dsl.builder_service import get_dsl_builder_service

        assert callable(get_dsl_builder_service)

    def test_save_result_class_exists(self) -> None:
        from src.backend.services.dsl.builder_service import SaveResult

        assert SaveResult is not None


class TestBuilderServiceUnknownAttribute:
    """Unknown attribute raises AttributeError."""

    def test_unknown_raises(self) -> None:
        from src.backend.services.dsl import builder_service

        with pytest.raises(AttributeError):
            _ = builder_service.__getattr__("nonexistent_xyz")
