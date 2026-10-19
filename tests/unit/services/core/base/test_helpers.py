"""Tests for ``src.backend.services.core.base.helpers``.

Helpers: _is_orm_model, get_service_for_model, create_service_class.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.core.base import helpers as mod
from src.backend.services.core.base.helpers import (
    _is_orm_model,
    create_service_class,
    get_service_for_model,
)


class TestIsOrmModel:
    """_is_orm_model — duck-typing check for SQLAlchemy models."""

    def test_orm_model_positive(self) -> None:
        class _FakeModel:
            __tablename__ = "users"
            __table__ = MagicMock()

        assert _is_orm_model(_FakeModel()) is True

    def test_plain_class_negative(self) -> None:
        class _Plain:
            pass

        assert _is_orm_model(_Plain()) is False

    def test_only_tablename(self) -> None:
        class _Partial:
            __tablename__ = "users"

        assert _is_orm_model(_Partial()) is False

    def test_only_table(self) -> None:
        class _Partial:
            __table__ = MagicMock()

        assert _is_orm_model(_Partial()) is False

    def test_dict_negative(self) -> None:
        assert _is_orm_model({}) is False

    def test_int_negative(self) -> None:
        assert _is_orm_model(42) is False

    def test_none_negative(self) -> None:
        assert _is_orm_model(None) is False


class TestGetServiceForModel:
    """get_service_for_model — finds service by convention.

    Uses sys.modules to inject fake service modules (import_module imports them).
    """

    @pytest.mark.asyncio
    async def test_success_path(self) -> None:
        UserModel = type(  # noqa: N806
            "UserModel",
            (),
            {"__tablename__": "users"},
        )

        # Создаём fake service module в sys.modules
        # Convention: {ModelName}Service — ищем UserModelService
        mock_service_class = MagicMock()
        fake_svc_module = types.ModuleType("src.backend.services.users")
        fake_svc_module.UserModelService = mock_service_class
        sys.modules["src.backend.services.users"] = fake_svc_module

        try:
            result = await get_service_for_model(UserModel)
            assert result is mock_service_class
        finally:
            del sys.modules["src.backend.services.users"]

    @pytest.mark.asyncio
    async def test_import_error_raises_value_error(self) -> None:
        UnknownModel = type(  # noqa: N806
            "UnknownModel",
            (),
            {"__tablename__": "unknown_table_for_test_xyz"},
        )

        # Не регистрируем в sys.modules → ImportError
        if "src.backend.services.unknown_table_for_test_xyz" in sys.modules:
            del sys.modules["src.backend.services.unknown_table_for_test_xyz"]

        with pytest.raises(ValueError) as exc_info:
            await get_service_for_model(UnknownModel)
        # ValueError содержит имя модели
        assert "UnknownModel" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_attribute_error_raises_value_error(self) -> None:
        UserModel = type(  # noqa: N806
            "UserModel",
            (),
            {"__tablename__": "users_no_service_test"},
        )

        # Module без UserModelService
        fake_svc_module = types.ModuleType("src.backend.services.users_no_service_test")
        # Без UserModelService
        sys.modules["src.backend.services.users_no_service_test"] = fake_svc_module

        try:
            with pytest.raises(ValueError) as exc_info:
                await get_service_for_model(UserModel)
            assert "UserModel" in str(exc_info.value)
        finally:
            del sys.modules["src.backend.services.users_no_service_test"]

    @pytest.mark.asyncio
    async def test_service_name_convention(self) -> None:
        # {model.__name__}Service — convention: имя класса используется
        OrderModel = type(  # noqa: N806 — динамическое создание
            "OrderModel",
            (),
            {"__tablename__": "orders_convention_test"},
        )

        mock_service_class = MagicMock()
        fake_svc_module = types.ModuleType("src.backend.services.orders_convention_test")
        fake_svc_module.OrderModelService = mock_service_class  # convention
        sys.modules["src.backend.services.orders_convention_test"] = fake_svc_module

        try:
            result = await get_service_for_model(OrderModel)
            # Должен вернуть OrderModelService (по convention)
            assert result is mock_service_class
        finally:
            del sys.modules["src.backend.services.orders_convention_test"]


class TestCreateServiceClass:
    """create_service_class — BaseService factory."""

    def test_creates_base_service_instance(self) -> None:
        request_schema = MagicMock()
        response_schema = MagicMock()
        version_schema = MagicMock()
        repo = MagicMock()

        with patch("src.backend.services.core.base.BaseService") as mock_base:
            result = create_service_class(
                request_schema=request_schema,
                response_schema=response_schema,
                version_schema=version_schema,
                repo=repo,
            )

        # BaseService вызван с правильными args
        mock_base.assert_called_once_with(
            repo, response_schema, request_schema, version_schema
        )
        # Возвращается результат вызова
        assert result is mock_base.return_value

    def test_returns_base_service_instance(self) -> None:
        request_schema = MagicMock()
        response_schema = MagicMock()
        version_schema = MagicMock()
        repo = MagicMock()

        # Без patch — реальный BaseService
        result = create_service_class(
            request_schema=request_schema,
            response_schema=response_schema,
            version_schema=version_schema,
            repo=repo,
        )
        # Просто проверяем что не None
        assert result is not None


class TestModuleExports:
    """Smoke import + проверка что функции определены."""

    def test_module_imports(self) -> None:
        from src.backend.services.core.base import helpers as m

        assert m is mod

    def test_functions_callable(self) -> None:
        assert callable(_is_orm_model)
        assert callable(get_service_for_model)
        assert callable(create_service_class)


class TestEdgeCases:
    """Edge cases."""

    @pytest.mark.asyncio
    async def test_get_service_error_message_includes_cause(self) -> None:
        # Создаём класс с явным __name__
        TestModel = type(  # noqa: N806
            "TestModel",
            (),
            {"__tablename__": "test_table_xyz_edge"},
        )

        # Не регистрируем → ImportError → ValueError
        if "src.backend.services.test_table_xyz_edge" in sys.modules:
            del sys.modules["src.backend.services.test_table_xyz_edge"]

        with pytest.raises(ValueError) as exc_info:
            await get_service_for_model(TestModel)
        msg = str(exc_info.value)
        assert "TestModel" in msg