"""Tests for ``src.backend.core.types.data_kind``.

W14.2: ``DataKind`` StrEnum — маркер формы данных в ``Message``.
- SINGLE (default) — одиночное событие
- BATCH — конечный список
- STREAM — асинхронный поток

StrEnum даёт прозрачную YAML/JSON сериализацию (``DataKind.SINGLE.value == "single"``).
"""

from __future__ import annotations

import json
from enum import StrEnum

import pytest

from src.backend.core.types.data_kind import DataKind


class TestDataKindMembers:
    """Проверка enum members."""

    def test_singleton_exists(self) -> None:
        assert hasattr(DataKind, "SINGLE")

    def test_batch_exists(self) -> None:
        assert hasattr(DataKind, "BATCH")

    def test_stream_exists(self) -> None:
        assert hasattr(DataKind, "STREAM")

    def test_total_three_members(self) -> None:
        """Только 3 значения: SINGLE, BATCH, STREAM."""
        assert len(DataKind) == 3

    def test_all_members_listed(self) -> None:
        assert set(DataKind.__members__) == {"SINGLE", "BATCH", "STREAM"}


class TestDataKindValues:
    """String values для YAML/JSON."""

    def test_singleton_value(self) -> None:
        assert DataKind.SINGLE.value == "single"

    def test_batch_value(self) -> None:
        assert DataKind.BATCH.value == "batch"

    def test_stream_value(self) -> None:
        assert DataKind.STREAM.value == "stream"

    def test_unique_values(self) -> None:
        """Все 3 values уникальны."""
        values = [d.value for d in DataKind]
        assert len(values) == len(set(values))


class TestDataKindStrEnumBehavior:
    """``DataKind`` наследуется от ``str`` — прозрачная сериализация."""

    def test_is_strenum_subclass(self) -> None:
        assert issubclass(DataKind, StrEnum)

    def test_is_str_subclass(self) -> None:
        """``StrEnum`` → ``DataKind`` member — это str."""
        assert isinstance(DataKind.SINGLE, str)

    def test_str_equality(self) -> None:
        """``DataKind.SINGLE == "single"`` (StrEnum — str)."""
        assert DataKind.SINGLE == "single"
        assert DataKind.BATCH == "batch"
        assert DataKind.STREAM == "stream"

    def test_str_concatenation(self) -> None:
        """``DataKind.SINGLE + "_type"`` работает как str."""
        assert DataKind.SINGLE + "_type" == "single_type"


class TestDataKindSerialization:
    """YAML/JSON-friendly."""

    def test_json_serialize(self) -> None:
        """JSON-сериализация через str."""
        data = json.dumps({"kind": DataKind.SINGLE})
        assert data == '{"kind": "single"}'

    def test_json_round_trip_str(self) -> None:
        """JSON round-trip через str value."""
        original = {"kind": "batch"}
        serialized = json.dumps(original)
        parsed = json.loads(serialized)
        assert DataKind(parsed["kind"]) == DataKind.BATCH


class TestDataKindLookup:
    """Lookup by value."""

    def test_lookup_by_value(self) -> None:
        """``DataKind("single")`` — constructor lookup by string value."""
        assert DataKind("single") == DataKind.SINGLE

    def test_lookup_batch(self) -> None:
        assert DataKind("batch") == DataKind.BATCH

    def test_lookup_invalid_raises(self) -> None:
        """Unknown value → ValueError (Enum behavior)."""
        with pytest.raises(ValueError):
            DataKind("unknown-kind")

    def test_lookup_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            DataKind("")


class TestDataKindEquality:
    """Equality and hashing."""

    def test_same_member_equal(self) -> None:
        assert DataKind.SINGLE == DataKind.SINGLE

    def test_different_members_not_equal(self) -> None:
        assert DataKind.SINGLE != DataKind.BATCH
        assert DataKind.BATCH != DataKind.STREAM
        assert DataKind.SINGLE != DataKind.STREAM

    def test_hashable(self) -> None:
        """Можно использовать как dict key / set member."""
        d = {DataKind.SINGLE: "s", DataKind.BATCH: "b", DataKind.STREAM: "t"}
        assert d[DataKind.SINGLE] == "s"
        assert d[DataKind.BATCH] == "b"

    def test_in_set(self) -> None:
        s = {DataKind.SINGLE, DataKind.BATCH}
        assert DataKind.SINGLE in s
        assert DataKind.STREAM not in s


class TestDataKindExports:
    """``__all__`` exports."""

    def test_exports(self) -> None:
        from src.backend.core.types import data_kind

        assert data_kind.__all__ == ("DataKind",)
