"""Tests for core/utils/converters.py (S98 — coverage push).

Pure value converters: numpy→Python, glob→regex, model→schema.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel


# ─── convert_numpy_types ──────────────────────────────────────────


def test_convert_numpy_bool() -> None:
    """numpy.bool_ → bool."""
    from src.backend.core.utils.converters import convert_numpy_types

    # True и False — bool наследуется от int в Python, но isinstance(bool, int) True.
    assert convert_numpy_types(True) is True
    assert convert_numpy_types(False) is False


def test_convert_numpy_int() -> None:
    """numpy.int64 → int."""
    from src.backend.core.utils.converters import convert_numpy_types

    fake_np_int = MagicMock(spec=["item"])
    fake_np_int.item = MagicMock(return_value=42)
    fake_np_int.__class__ = int  # will be cast to int
    result = convert_numpy_types(42)
    assert result == 42
    assert isinstance(result, int)


def test_convert_numpy_float() -> None:
    """float → float."""
    from src.backend.core.utils.converters import convert_numpy_types

    result = convert_numpy_types(3.14)
    assert result == 3.14
    assert isinstance(result, float)


def test_convert_numpy_scalar_with_item() -> None:
    """Object с .item() method → .item() result."""
    from src.backend.core.utils.converters import convert_numpy_types

    class FakeNumpyScalar:
        def item(self) -> int:
            return 99

    result = convert_numpy_types(FakeNumpyScalar())
    assert result == 99


def test_convert_numpy_item_raises_returns_original() -> None:
    """Object с .item() который raises → return value as-is."""
    from src.backend.core.utils.converters import convert_numpy_types

    class FakeBadItem:
        def item(self) -> None:
            raise ValueError("cannot convert")

    fake = FakeBadItem()
    # Should not raise, returns original.
    assert convert_numpy_types(fake) is fake


def test_convert_numpy_passthrough() -> None:
    """Non-numpy objects → возвращает as-is."""
    from src.backend.core.utils.converters import convert_numpy_types

    assert convert_numpy_types("string") == "string"
    assert convert_numpy_types([1, 2, 3]) == [1, 2, 3]
    assert convert_numpy_types({"key": "val"}) == {"key": "val"}
    assert convert_numpy_types(None) is None


# ─── convert_pattern ──────────────────────────────────────────────


def test_convert_pattern_root_path() -> None:
    """'/' → '^/$' (root path special case)."""
    from src.backend.core.utils.converters import convert_pattern

    assert convert_pattern("/") == "^/$"


def test_convert_pattern_simple() -> None:
    """Simple pattern без wildcard."""
    from src.backend.core.utils.converters import convert_pattern

    assert convert_pattern("foo") == "^.*foo$"


def test_convert_pattern_with_wildcard() -> None:
    """'*' → '.*'."""
    from src.backend.core.utils.converters import convert_pattern

    assert convert_pattern("/api/*/users") == "^.*/api/.*/users$"


def test_convert_pattern_multiple_wildcards() -> None:
    """Multiples '*' → '.*' (each occurrence replaced)."""
    from src.backend.core.utils.converters import convert_pattern

    # "*.*" → .replace('*', '.*') = ".*.*" → " ^.*" + ".*.*" + "$" = "^.*.*..*$"
    assert convert_pattern("*.*") == "^.*.*..*$"


# ─── transfer_model_to_schema ─────────────────────────────────────


def test_transfer_model_to_schema_success() -> None:
    """Valid dict → Pydantic schema instance."""
    from src.backend.core.utils.converters import transfer_model_to_schema

    class User(BaseModel):
        name: str
        age: int

    schema = transfer_model_to_schema({"name": "Alice", "age": 30}, User)
    assert schema.name == "Alice"
    assert schema.age == 30


def test_transfer_model_to_schema_from_attributes() -> None:
    """from_attributes=True для ORM-style объекты."""
    from src.backend.core.utils.converters import transfer_model_to_schema

    class User(BaseModel):
        name: str

        model_config = {"from_attributes": True}

    class ORMUser:
        name = "Bob"

    schema = transfer_model_to_schema(ORMUser(), User, from_attributes=True)
    assert schema.name == "Bob"


def test_transfer_model_to_schema_invalid_raises_value_error() -> None:
    """Invalid input → ValueError (НЕ original Pydantic exception)."""
    from src.backend.core.utils.converters import transfer_model_to_schema

    class User(BaseModel):
        name: str
        age: int

    with pytest.raises(ValueError, match="Ошибка преобразования"):
        transfer_model_to_schema({"name": "Alice"}, User)  # missing 'age'


def test_transfer_model_to_schema_wrong_type_raises_value_error() -> None:
    """Wrong type → ValueError."""
    from src.backend.core.utils.converters import transfer_model_to_schema

    class User(BaseModel):
        name: str
        age: int

    with pytest.raises(ValueError, match="Ошибка преобразования"):
        transfer_model_to_schema({"name": "Alice", "age": "not-int"}, User)


def test_converters_module_dunder_all() -> None:
    """__all__ содержит 3 функции."""
    import src.backend.core.utils.converters as mod

    assert mod.__all__ == (
        "convert_numpy_types",
        "convert_pattern",
        "transfer_model_to_schema",
    )
