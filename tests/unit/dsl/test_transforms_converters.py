"""Tests for DSL data transform converters (dsl/transforms/converters.py).

Wave: [tech-debt/coverage].
"""

from __future__ import annotations

import pytest

from src.backend.dsl.transforms.converters import (
    coalesce_fields,
    drop_fields,
    flatten_dict,
    glom_transform,
    hash_field,
    pick_fields,
    rename_fields,
)


class TestFlattenDict:
    """Tests for flatten_dict."""

    def test_simple_nested(self) -> None:
        data = {"a": {"b": 1, "c": {"d": 2}}}
        result = flatten_dict(data)
        assert result == {"a.b": 1, "a.c.d": 2}

    def test_flat_dict_unchanged(self) -> None:
        data = {"x": 1, "y": 2}
        assert flatten_dict(data) == {"x": 1, "y": 2}

    def test_custom_separator(self) -> None:
        data = {"a": {"b": 1}}
        result = flatten_dict(data, separator="_")
        assert result == {"a_b": 1}

    def test_custom_prefix(self) -> None:
        data = {"a": {"b": 1}}
        result = flatten_dict(data, prefix="root")
        assert result == {"root.a.b": 1}

    def test_empty_dict(self) -> None:
        assert flatten_dict({}) == {}


class TestPickFields:
    """Tests for pick_fields."""

    def test_picks_specified(self) -> None:
        data = {"a": 1, "b": 2, "c": 3}
        assert pick_fields(data, "a", "c") == {"a": 1, "c": 3}

    def test_empty_result_when_no_match(self) -> None:
        data = {"a": 1}
        assert pick_fields(data, "z") == {}

    def test_empty_input(self) -> None:
        assert pick_fields({}, "a") == {}


class TestDropFields:
    """Tests for drop_fields."""

    def test_drops_specified(self) -> None:
        data = {"a": 1, "b": 2, "c": 3}
        assert drop_fields(data, "b") == {"a": 1, "c": 3}

    def test_drops_multiple(self) -> None:
        data = {"a": 1, "b": 2, "c": 3}
        assert drop_fields(data, "a", "c") == {"b": 2}

    def test_no_match_leaves_unchanged(self) -> None:
        data = {"a": 1}
        assert drop_fields(data, "z") == {"a": 1}


class TestRenameFields:
    """Tests for rename_fields."""

    def test_renames_specified(self) -> None:
        data = {"old": 1, "keep": 2}
        assert rename_fields(data, {"old": "new"}) == {"new": 1, "keep": 2}

    def test_unchanged_when_not_in_mapping(self) -> None:
        data = {"a": 1}
        assert rename_fields(data, {"z": "w"}) == {"a": 1}

    def test_empty_mapping(self) -> None:
        data = {"a": 1}
        assert rename_fields(data, {}) == {"a": 1}


class TestHashField:
    """Tests for hash_field."""

    def test_hashes_existing_field(self) -> None:
        data = {"pwd": "secret"}
        result = hash_field(data, "pwd")
        assert result["pwd"] != "secret"
        assert len(result["pwd"]) == 64  # sha256 hex

    def test_default_algorithm(self) -> None:
        data = {"x": "y"}
        result = hash_field(data, "x")
        # sha256 produces 64-char hex
        assert len(result["x"]) == 64

    def test_md5_algorithm(self) -> None:
        data = {"x": "y"}
        result = hash_field(data, "x", algorithm="md5")
        assert len(result["x"]) == 32

    def test_missing_field_unchanged(self) -> None:
        data = {"a": 1}
        assert hash_field(data, "z") == {"a": 1}

    def test_preserves_other_fields(self) -> None:
        data = {"a": 1, "b": 2}
        result = hash_field(data, "a")
        assert result["b"] == 2


class TestCoalesceFields:
    """Tests for coalesce_fields."""

    def test_first_non_none_used(self) -> None:
        data = {"a": 1, "b": 2}
        result = coalesce_fields(data, "target", "a", "b")
        assert result["target"] == 1

    def test_skips_none(self) -> None:
        data = {"a": None, "b": 2}
        result = coalesce_fields(data, "target", "a", "b")
        assert result["target"] == 2

    def test_uses_default_when_all_none(self) -> None:
        data = {"a": None}
        result = coalesce_fields(data, "target", "a", "b", default="fallback")
        assert result["target"] == "fallback"

    def test_none_default_when_no_match(self) -> None:
        data = {}
        result = coalesce_fields(data, "target", "a")
        assert result["target"] is None

    def test_preserves_existing_data(self) -> None:
        data = {"a": 1, "c": 3}
        result = coalesce_fields(data, "target", "a")
        assert result["c"] == 3


class TestGlomTransform:
    """Tests for glom_transform."""

    def test_basic_path(self) -> None:
        data = {"user": {"name": "Alice"}}
        transform = glom_transform({"user_name": "user.name"})
        assert transform(data) == {"user_name": "Alice"}

    def test_nested_path(self) -> None:
        data = {"a": {"b": {"c": 42}}}
        transform = glom_transform({"val": "a.b.c"})
        assert transform(data) == {"val": 42}

    def test_multiple_fields(self) -> None:
        data = {"x": 1, "y": 2}
        transform = glom_transform({"first": "x", "second": "y"})
        assert transform(data) == {"first": 1, "second": 2}

    def test_missing_path_raises(self) -> None:
        data = {"a": 1}
        transform = glom_transform({"z": "nonexistent.path"})
        with pytest.raises(Exception):  # glom raises PathAccessError
            transform(data)
