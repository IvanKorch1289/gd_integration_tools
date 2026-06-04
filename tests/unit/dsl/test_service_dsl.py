"""Unit tests for ServiceDSLRegistry and decorators."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.backend.dsl.service_dsl import (
    ServiceDSLRegistry,
    ServiceMeta,
    register_action,
    scan_and_register_actions,
    service_dsl,
    service_dsl_registry,
)


class TestServiceMeta:
    def test_defaults(self) -> None:
        meta = ServiceMeta(
            name="orders", service_cls=MagicMock, service_getter=lambda: None
        )
        assert meta.crud is True
        assert meta.protocols == ("all",)
        assert meta.methods == []


class TestServiceDSLRegistry:
    @pytest.fixture
    def registry(self) -> ServiceDSLRegistry:
        return ServiceDSLRegistry()

    def test_register_and_get(self, registry: ServiceDSLRegistry) -> None:
        meta = ServiceMeta(
            name="orders", service_cls=MagicMock, service_getter=lambda: None
        )
        registry.register(meta)
        assert registry.get("orders") is meta

    def test_list_services(self, registry: ServiceDSLRegistry) -> None:
        meta1 = ServiceMeta(
            name="a", service_cls=MagicMock, service_getter=lambda: None
        )
        meta2 = ServiceMeta(
            name="b", service_cls=MagicMock, service_getter=lambda: None
        )
        registry.register(meta1)
        registry.register(meta2)
        assert len(registry.list_services()) == 2

    def test_register_all_actions(self, registry: ServiceDSLRegistry) -> None:
        class Svc:
            def add(self) -> None: ...

            def custom(self) -> None: ...

        meta = ServiceMeta(
            name="orders",
            service_cls=Svc,
            service_getter=lambda: Svc(),
            methods=["custom"],
        )
        registry.register(meta)
        with patch(
            "src.backend.dsl.commands.registry.action_handler_registry"
        ) as mock_reg:
            registry.register_all_actions()
            assert mock_reg.register.call_count == 2  # add, custom


class TestServiceDSL:
    def test_decorator(self) -> None:
        @service_dsl(name="invoices")
        class InvoiceService:
            async def create(self, data: Any) -> None: ...

            async def approve(self, invoice_id: str) -> None: ...

        assert hasattr(InvoiceService, "_service_dsl_meta")
        meta = InvoiceService._service_dsl_meta
        assert meta.name == "invoices"
        assert "create" in meta.methods
        assert "approve" in meta.methods

    def test_decorator_with_options(self) -> None:
        class In(BaseModel):
            x: int

        @service_dsl(
            name="test", schema_in=In, protocols=["rest"], crud=False, methods=["run"]
        )
        class TestService:
            def run(self) -> None: ...

        meta = TestService._service_dsl_meta
        assert meta.schema_in is In
        assert meta.protocols == ["rest"]
        assert meta.crud is False
        assert meta.methods == ["run"]


class TestRegisterAction:
    def test_decorator(self) -> None:
        @register_action("orders.create")
        def create_order() -> None: ...

        assert hasattr(create_order, "_action_meta")
        assert create_order._action_meta["action"] == "orders.create"


class TestScanAndRegister:
    def test_scan_empty(self) -> None:
        count = scan_and_register_actions(package_paths=[])
        assert count == 0
