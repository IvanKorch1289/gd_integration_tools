"""Unit tests for src.backend.dsl.builders.collection_mixin (K3 W1, S39)."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from src.backend.dsl.builders.collection_mixin import CollectionMixin


class TestCollect:
    def test_collect_simple(self) -> None:
        result = CollectionMixin.collect(
            [{"name": "a"}, {"name": "b"}, {"name": "c"}], field="name"
        )
        assert result == ["a", "b", "c"]

    def test_collect_nested_field(self) -> None:
        # Top-level only for now
        result = CollectionMixin.collect([{"x": 1}, {"x": 2}], field="x")
        assert result == [1, 2]

    def test_collect_missing_field(self) -> None:
        result = CollectionMixin.collect([{"name": "a"}, {"age": 5}], field="name")
        assert result == ["a", None]

    def test_collect_no_field(self) -> None:
        result = CollectionMixin.collect([1, 2, 3], field=None)
        assert result == [1, 2, 3]


class TestFindAll:
    def test_find_all_callable(self) -> None:
        items = [1, 2, 3, 4, 5]
        result = CollectionMixin.find_all(items, predicate=lambda x: x > 2)
        assert result == [3, 4, 5]

    def test_find_all_field_value(self) -> None:
        items = [{"age": 10}, {"age": 20}, {"age": 30}]
        result = CollectionMixin.find_all(items, field="age", value=20)
        assert result == [{"age": 20}]

    def test_find_all_empty(self) -> None:
        assert CollectionMixin.find_all([], predicate=lambda x: True) == []

    def test_find_all_no_predicate(self) -> None:
        items = [1, 2, 3]
        result = CollectionMixin.find_all(items)
        assert result == [1, 2, 3]


class TestFind:
    def test_find_callable(self) -> None:
        items = [1, 2, 3, 4, 5]
        result = CollectionMixin.find(items, predicate=lambda x: x > 3)
        assert result == 4

    def test_find_not_found(self) -> None:
        items = [1, 2, 3]
        result = CollectionMixin.find(items, predicate=lambda x: x > 10)
        assert result is None

    def test_find_field_value(self) -> None:
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = CollectionMixin.find(items, field="id", value=2)
        assert result == {"id": 2}


class TestGroupBy:
    def test_group_by_basic(self) -> None:
        items = [
            {"category": "A", "name": "x"},
            {"category": "B", "name": "y"},
            {"category": "A", "name": "z"},
        ]
        result = CollectionMixin.group_by(items, field="category")
        assert len(result["A"]) == 2
        assert len(result["B"]) == 1
        assert result["A"][0]["name"] == "x"
        assert result["A"][1]["name"] == "z"


class TestSort:
    def test_sort_by_field(self) -> None:
        items = [{"age": 30}, {"age": 10}, {"age": 20}]
        result = CollectionMixin.sort(items, field="age")
        assert [x["age"] for x in result] == [10, 20, 30]

    def test_sort_reverse(self) -> None:
        items = [{"age": 10}, {"age": 30}, {"age": 20}]
        result = CollectionMixin.sort(items, field="age", reverse=True)
        assert [x["age"] for x in result] == [30, 20, 10]

    def test_sort_primitives(self) -> None:
        result = CollectionMixin.sort([3, 1, 2])
        assert result == [1, 2, 3]


class TestEach:
    def test_each_returns_original(self) -> None:
        items = [1, 2, 3]
        side_effect: list[int] = []
        result = CollectionMixin.each(items, action=side_effect.append)
        assert result == items
        assert side_effect == [1, 2, 3]


class TestFlatten:
    def test_flatten_1_level(self) -> None:
        result = CollectionMixin.flatten([[1, 2], [3, 4]])
        assert result == [1, 2, 3, 4]

    def test_flatten_2_levels(self) -> None:
        result = CollectionMixin.flatten([[[1]], [[2]]], levels=2)
        assert result == [1, 2]

    def test_flatten_mixed(self) -> None:
        result = CollectionMixin.flatten([1, [2, 3], 4])
        assert result == [1, 2, 3, 4]


class TestUnique:
    def test_unique_primitives(self) -> None:
        result = CollectionMixin.unique([1, 2, 2, 3, 1, 4])
        assert result == [1, 2, 3, 4]

    def test_unique_by_field(self) -> None:
        items = [
            {"email": "a@x.com", "name": "Alice"},
            {"email": "b@x.com", "name": "Bob"},
            {"email": "a@x.com", "name": "Alice2"},
        ]
        result = CollectionMixin.unique(items, field="email")
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"


class TestPlus:
    def test_plus_list_list(self) -> None:
        assert CollectionMixin.plus([1, 2], [3, 4]) == [1, 2, 3, 4]

    def test_plus_list_tuple(self) -> None:
        assert CollectionMixin.plus([1, 2], (3, 4)) == [1, 2, 3, 4]

    def test_plus_list_set(self) -> None:
        result = CollectionMixin.plus([1, 2], {3, 4})
        assert sorted(result) == [1, 2, 3, 4]


class TestEdgeCases:
    def test_empty_input(self) -> None:
        assert CollectionMixin.collect([], field="x") == []
        assert CollectionMixin.find_all([], predicate=lambda x: True) == []
        assert CollectionMixin.find([], predicate=lambda x: True) is None
        assert CollectionMixin.group_by([], field="x") == {}
        assert CollectionMixin.sort([], field="x") == []
        assert CollectionMixin.each([], action=lambda x: x) == []
        assert CollectionMixin.flatten([]) == []
        assert CollectionMixin.unique([]) == []
        assert CollectionMixin.plus([], []) == []

    def test_none_input_returns_empty(self) -> None:
        assert CollectionMixin.collect(None, field="x") == []
        assert CollectionMixin.find_all(None, predicate=lambda x: True) == []
        assert CollectionMixin.find(None, predicate=lambda x: True) is None

    def test_thread_safe(self) -> None:
        """Static methods should be thread-safe (no shared state)."""
        results: list[Any] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for i in range(100):
                    r = CollectionMixin.find_all(
                        list(range(100)), predicate=lambda x, v=i: x == v
                    )
                    results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 500


@pytest.fixture
def smoke_route() -> None:
    """Smoke test: verify import + class structure."""
    assert hasattr(CollectionMixin, "collect")
    assert hasattr(CollectionMixin, "find_all")
    assert hasattr(CollectionMixin, "find")
    assert hasattr(CollectionMixin, "group_by")
    assert hasattr(CollectionMixin, "sort")
    assert hasattr(CollectionMixin, "each")
    assert hasattr(CollectionMixin, "flatten")
    assert hasattr(CollectionMixin, "unique")
    assert hasattr(CollectionMixin, "plus")
