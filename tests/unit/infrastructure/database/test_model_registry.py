"""Unit tests for model_registry."""

from __future__ import annotations

from enum import Enum
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.database.model_registry import (
    get_model_enum,
    get_user_models,
)
from src.backend.infrastructure.database.models.base import BaseModel


class TestGetUserModels:
    """Tests for get_user_models."""

    @pytest.mark.unit
    def test_returns_empty_dict_when_no_mappers(self) -> None:
        """Returns empty dict when mapper_registry has no mappers."""
        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = []
            result = get_user_models()
            assert result == {}

    @pytest.mark.unit
    def test_excludes_base_model(self) -> None:
        """Excludes BaseModel itself from results."""
        mock_mapper = MagicMock()
        mock_mapper.class_ = BaseModel

        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = [mock_mapper]
            result = get_user_models()
            assert result == {}

    @pytest.mark.unit
    def test_includes_subclasses_of_base_model(self) -> None:
        """Includes concrete subclasses of BaseModel."""

        class FakeModel(BaseModel):
            __tablename__ = "fake_models"

        mock_mapper = MagicMock()
        mock_mapper.class_ = FakeModel

        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = [mock_mapper]
            result = get_user_models()
            assert "fake_models" in result
            assert result["fake_models"] is FakeModel

    @pytest.mark.unit
    def test_skips_non_base_model_classes(self) -> None:
        """Skips classes that do not inherit from BaseModel."""

        class NotAModel:
            __tablename__ = "not_a_model"

        mock_mapper = MagicMock()
        mock_mapper.class_ = NotAModel

        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = [mock_mapper]
            result = get_user_models()
            assert "not_a_model" not in result

    @pytest.mark.unit
    def test_skips_non_type_objects(self) -> None:
        """Skips objects that are not instances of type."""
        mock_mapper = MagicMock()
        mock_mapper.class_ = "not_a_class"

        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = [mock_mapper]
            result = get_user_models()
            assert result == {}

    @pytest.mark.unit
    def test_multiple_mappers(self) -> None:
        """Correctly processes multiple mappers."""

        class ModelA(BaseModel):
            __tablename__ = "model_a"

        class ModelB(BaseModel):
            __tablename__ = "model_b"

        mock_mapper_a = MagicMock()
        mock_mapper_a.class_ = ModelA
        mock_mapper_b = MagicMock()
        mock_mapper_b.class_ = ModelB

        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = [mock_mapper_a, mock_mapper_b]
            result = get_user_models()
            assert len(result) == 2
            assert result["model_a"] is ModelA
            assert result["model_b"] is ModelB


class TestGetModelEnum:
    """Tests for get_model_enum."""

    @pytest.mark.unit
    def test_returns_enum_class(self) -> None:
        """Returns an Enum subclass."""
        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = []
            result = get_model_enum()
            assert issubclass(result, Enum)

    @pytest.mark.unit
    def test_enum_members_match_models(self) -> None:
        """Enum members correspond to model names."""

        class TestModel(BaseModel):
            __tablename__ = "test_models"

        mock_mapper = MagicMock()
        mock_mapper.class_ = TestModel

        with patch(
            "src.backend.infrastructure.database.model_registry.mapper_registry"
        ) as mock_registry:
            mock_registry.mappers = [mock_mapper]
            ModelEnum = get_model_enum()
            assert hasattr(ModelEnum, "test_models")
            assert ModelEnum.test_models.value is TestModel
