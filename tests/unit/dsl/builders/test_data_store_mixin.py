"""Unit-тесты DataStoreMixin (S39 W3a — n8n-style in-memory KV с TTL + thread-safety).

Покрытие:
    * Базовые операции get/set/delete/has.
    * Default value при get.
    * Итераторы keys/values/items (lazy expiry).
    * size() / clear().
    * TTL expiry (lazy, на чтении).
    * TTL=None = no expiry.
    * Thread-safety (concurrent set/get из N потоков).
    * Named stores isolation.
    * Persistence через multi-step route.
    * Complex values (dict/list) preserved.
    * set(key, None) и get round-trip.
    * MRO/RouteBuilder integration.
    * get-or-create semantics.
"""

# ruff: noqa: S101

from __future__ import annotations

import threading
import time

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.data_store_mixin import DataStore, DataStoreMixin


@pytest.fixture
def store() -> DataStore:
    return DataStore(name="test")


@pytest.fixture
def builder() -> RouteBuilder:
    return RouteBuilder.from_("test_route", source="internal:test")


# ── Basic CRUD ──


class TestBasicCRUD:
    def test_data_store_get_set(self, store: DataStore) -> None:
        store.set("foo", "bar")
        assert store.get("foo") == "bar"

    def test_data_store_default(self, store: DataStore) -> None:
        assert store.get("missing", default="fallback") == "fallback"
        assert store.get("missing") is None

    def test_data_store_delete(self, store: DataStore) -> None:
        store.set("k", 1)
        assert store.delete("k") is True
        assert store.delete("k") is False
        assert not store.has("k")

    def test_data_store_has(self, store: DataStore) -> None:
        assert not store.has("k")
        store.set("k", "v")
        assert store.has("k")


# ── Iterators ──


class TestIterators:
    def test_data_store_keys(self, store: DataStore) -> None:
        store.set("a", 1)
        store.set("b", 2)
        assert sorted(store.keys()) == ["a", "b"]

    def test_data_store_values(self, store: DataStore) -> None:
        store.set("a", 1)
        store.set("b", 2)
        assert sorted(store.values()) == [1, 2]

    def test_data_store_items(self, store: DataStore) -> None:
        store.set("a", 1)
        store.set("b", 2)
        assert sorted(store.items()) == [("a", 1), ("b", 2)]

    def test_data_store_clear(self, store: DataStore) -> None:
        store.set("a", 1)
        store.set("b", 2)
        store.clear()
        assert store.size() == 0
        assert store.keys() == []

    def test_data_store_size(self, store: DataStore) -> None:
        assert store.size() == 0
        store.set("a", 1)
        store.set("b", 2)
        assert store.size() == 2


# ── TTL ──


class TestTTL:
    def test_data_store_ttl(self, store: DataStore) -> None:
        store.set("k", "v", ttl_seconds=0)
        time.sleep(0.05)
        assert store.get("k") is None
        assert not store.has("k")

    def test_data_store_ttl_unset(self, store: DataStore) -> None:
        store.set("k", "v", ttl_seconds=None)
        time.sleep(0.05)
        assert store.get("k") == "v"
        assert store.has("k")

    def test_data_store_ttl_does_not_affect_other_keys(self, store: DataStore) -> None:
        store.set("ephemeral", "x", ttl_seconds=0)
        store.set("permanent", "y")
        time.sleep(0.05)
        assert store.get("ephemeral") is None
        assert store.get("permanent") == "y"


# ── Thread-safety ──


class TestThreadSafety:
    def test_data_store_thread_safe(self, store: DataStore) -> None:
        n_threads = 8
        n_per_thread = 200
        errors: list[BaseException] = []

        def worker(tid: int) -> None:
            try:
                for i in range(n_per_thread):
                    key = f"t{tid}_k{i}"
                    store.set(key, i)
                    assert store.get(key) == i
                    assert store.has(key)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors[:3]}"
        assert store.size() == n_threads * n_per_thread


# ── Named stores & isolation ──


class TestNamedStores:
    def test_data_store_named(self, builder: RouteBuilder) -> None:
        s1 = builder.data_store("alpha")
        s2 = builder.data_store("beta")
        s3 = builder.data_store("alpha")
        assert s1 is not s2  # different names -> different instances
        assert s1 is s3  # same name -> same instance

    def test_data_store_named_isolation(self, builder: RouteBuilder) -> None:
        s1 = builder.data_store("alpha")
        s2 = builder.data_store("beta")
        s1.set("shared_key", "from_alpha")
        s2.set("shared_key", "from_beta")
        assert s1.get("shared_key") == "from_alpha"
        assert s2.get("shared_key") == "from_beta"

    def test_data_store_persistence_across_steps(self, builder: RouteBuilder) -> None:
        store = builder.data_store("workflow")
        store.set("step1_result", {"value": 42})
        # Simulate step 2
        retrieved = store.get("step1_result")
        assert retrieved == {"value": 42}
        # And step 3
        store.set("step2_result", retrieved["value"] * 2)
        assert store.get("step2_result") == 84


# ── Value types ──


class TestValueTypes:
    def test_data_store_complex_values(self, store: DataStore) -> None:
        complex_v = {"nested": {"a": [1, 2, 3]}, "b": None, "c": (1, 2)}
        store.set("obj", complex_v)
        assert store.get("obj") == complex_v

    def test_data_store_list_values(self, store: DataStore) -> None:
        store.set("lst", [1, "two", {"k": 3}])
        assert store.get("lst") == [1, "two", {"k": 3}]

    def test_data_store_none_value(self, store: DataStore) -> None:
        store.set("k", None)
        # None stored explicitly should not return the default
        assert store.get("k") is None
        # has() must still see it
        assert store.has("k")
        # And get with explicit default returns None (not default)
        assert store.get("k", default="fallback") is None


# ── Mixin integration with RouteBuilder ──


class TestRouteBuilderIntegration:
    def test_mixin_in_mro(self, builder: RouteBuilder) -> None:
        mro = [c.__name__ for c in type(builder).__mro__]
        assert "DataStoreMixin" in mro
        assert "DataStoreStepMixin" in mro

    def test_data_store_default_name(self, builder: RouteBuilder) -> None:
        store = builder.data_store()
        assert store.name == "default"
        assert store.backend == "memory"

    def test_data_store_multi_step_route(self, builder: RouteBuilder) -> None:
        # Simulate a multi-step workflow using the data store
        workflow_store = builder.data_store("etl")

        # Step 1: extract
        workflow_store.set("raw_data", [{"id": i} for i in range(3)])

        # Step 2: transform (uses data from step 1)
        raw = workflow_store.get("raw_data")
        transformed = [{"uid": r["id"]} for r in raw]
        workflow_store.set("transformed", transformed)

        # Step 3: persist
        result = workflow_store.get("transformed")
        assert result == [{"uid": 0}, {"uid": 1}, {"uid": 2}]
        assert workflow_store.size() == 2

    def test_data_store_per_builder_isolation(self) -> None:
        b1 = RouteBuilder.from_("route1", source="t")
        b2 = RouteBuilder.from_("route2", source="t")
        s1 = b1.data_store("default")
        s2 = b2.data_store("default")
        # Different builder instances -> different stores
        assert s1 is not s2
        s1.set("k", "from_b1")
        s2.set("k", "from_b2")
        assert s1.get("k") == "from_b1"
        assert s2.get("k") == "from_b2"

    def test_data_store_class_protocol(self) -> None:
        # DataStore class is exported and has the expected public API
        expected_methods = {"get", "set", "delete", "has", "keys", "values",
                            "items", "clear", "size", "name", "backend"}
        for m in expected_methods:
            assert hasattr(DataStore, m), f"DataStore missing method: {m}"

    def test_data_store_mixin_protocol(self) -> None:
        # DataStoreMixin has the expected public API
        assert hasattr(DataStoreMixin, "data_store")
        assert callable(DataStoreMixin.data_store)
