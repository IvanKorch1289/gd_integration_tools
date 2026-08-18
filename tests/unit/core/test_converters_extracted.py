"""TDD characterization для dsl/codec/converters.py → core/utils/ extraction (Candidate #10).

BEFORE refactor — verify current behavior of all 3 functions.
After refactor — verify they still work from both locations.
"""

from __future__ import annotations

import pytest


class TestConvertNumpyTypes:
    """convert_numpy_types — конвертация numpy/Arrow scalars в native types."""

    def test_bool_passthrough(self) -> None:
        from src.backend.dsl.codec.converters import convert_numpy_types

        assert convert_numpy_types(True) is True
        assert convert_numpy_types(False) is False

    def test_int_passthrough(self) -> None:
        from src.backend.dsl.codec.converters import convert_numpy_types

        result = convert_numpy_types(42)
        assert result == 42
        assert isinstance(result, int)

    def test_float_passthrough(self) -> None:
        from src.backend.dsl.codec.converters import convert_numpy_types

        result = convert_numpy_types(3.14)
        assert result == 3.14
        assert isinstance(result, float)

    def test_string_passthrough(self) -> None:
        from src.backend.dsl.codec.converters import convert_numpy_types

        assert convert_numpy_types("hello") == "hello"

    def test_none_passthrough(self) -> None:
        from src.backend.dsl.codec.converters import convert_numpy_types

        assert convert_numpy_types(None) is None

    def test_list_passthrough(self) -> None:
        from src.backend.dsl.codec.converters import convert_numpy_types

        assert convert_numpy_types([1, 2, 3]) == [1, 2, 3]

    def test_dict_passthrough(self) -> None:
        from src.backend.dsl.codec.converters import convert_numpy_types

        assert convert_numpy_types({"a": 1}) == {"a": 1}

    def test_object_with_item_method(self) -> None:
        """Objects с .item() method (numpy scalars) вызывают .item()."""
        from src.backend.dsl.codec.converters import convert_numpy_types

        class FakeNumpyScalar:
            def item(self):
                return 42

        result = convert_numpy_types(FakeNumpyScalar())
        assert result == 42

    def test_object_with_failing_item_method(self) -> None:
        """Objects с failing .item() → return value as-is."""
        from src.backend.dsl.codec.converters import convert_numpy_types

        class FakeFailing:
            def item(self):
                raise ValueError("boom")

        value = FakeFailing()
        result = convert_numpy_types(value)
        assert result is value


class TestConvertPattern:
    """convert_pattern — Glob → regex conversion."""

    def test_root_path_anchored_at_both_ends(self) -> None:
        from src.backend.dsl.codec.converters import convert_pattern

        result = convert_pattern("/")
        assert result == "^/$"

    def test_path_with_wildcard_anchored(self) -> None:
        from src.backend.dsl.codec.converters import convert_pattern

        result = convert_pattern("/api/*")
        assert result == "^.*/api/.*$"

    def test_multiple_wildcards_converted(self) -> None:
        from src.backend.dsl.codec.converters import convert_pattern

        result = convert_pattern("/api/v1/*/users/*")
        assert result == "^.*/api/v1/.*/users/.*$"

    def test_no_wildcards_simple_anchored(self) -> None:
        from src.backend.dsl.codec.converters import convert_pattern

        result = convert_pattern("/api/v1")
        assert result == "^.*/api/v1$"


class TestTransferModelToSchema:
    """transfer_model_to_schema — ORM/dict → pydantic schema."""

    def test_dict_to_pydantic_schema(self) -> None:
        from src.backend.dsl.codec.converters import transfer_model_to_schema
        from pydantic import BaseModel

        class UserSchema(BaseModel):
            name: str
            age: int

        result = transfer_model_to_schema(
            {"name": "Alice", "age": 30}, UserSchema,
        )
        assert result.name == "Alice"
        assert result.age == 30

    def test_invalid_data_raises_value_error(self) -> None:
        from src.backend.dsl.codec.converters import transfer_model_to_schema
        from pydantic import BaseModel

        class UserSchema(BaseModel):
            name: str
            age: int

        with pytest.raises(ValueError, match="Ошибка преобразования"):
            transfer_model_to_schema(
                {"name": "Alice", "age": "not_a_number"}, UserSchema,
            )

    def test_from_attributes_true(self) -> None:
        """from_attributes=True: pydantic может читать атрибуты объекта."""
        from src.backend.dsl.codec.converters import transfer_model_to_schema
        from pydantic import BaseModel

        class UserSchema(BaseModel):
            name: str
            age: int

        class UserObj:
            name = "Bob"
            age = 25

        result = transfer_model_to_schema(
            UserObj(), UserSchema, from_attributes=True,
        )
        assert result.name == "Bob"
        assert result.age == 25


class TestCoreUtilsConvertersImport:
    """После refactor — должно работать также из core/utils/converters.py."""

    def test_core_utils_converters_all_exports(self) -> None:
        from src.backend.core.utils import converters

        assert "convert_numpy_types" in converters.__all__
        assert "convert_pattern" in converters.__all__
        assert "transfer_model_to_schema" in converters.__all__

    def test_core_utils_symbols_identity(self) -> None:
        """core/utils/converters.py functions — это SAME objects as dsl shim."""
        from src.backend.core.utils import converters as core_mod
        from src.backend.dsl.codec import converters as dsl_mod

        assert core_mod.convert_numpy_types is dsl_mod.convert_numpy_types
        assert core_mod.convert_pattern is dsl_mod.convert_pattern
        assert core_mod.transfer_model_to_schema is dsl_mod.transfer_model_to_schema
