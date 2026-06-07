"""Unit-тесты ConsulConfigStore.

Mock-уровень: consul.Consul полностью мокируется,
чтобы не требовать running Consul в unit-тестах.
"""

# ruff: noqa: S101

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.consul_config import ConsulConfigStore


class TestConsulConfigStore:
    """Сценарии KV-get / put / watch."""

    @pytest.fixture
    def store(self) -> ConsulConfigStore:
        return ConsulConfigStore(host="consul.test", port=8500)

    @pytest.fixture
    def mock_consul(self) -> MagicMock:
        with patch("consul.Consul") as m:
            yield m.return_value

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    def test_get_returns_value(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.get.return_value = (1, {"Value": b"hello"})
        assert store.get("key") == "hello"
        mock_consul.kv.get.assert_called_once_with("key")

    def test_get_returns_default_when_missing(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.get.return_value = (1, None)
        assert store.get("missing", default="fallback") == "fallback"

    def test_get_uses_cache(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.get.return_value = (1, {"Value": b"cached"})
        assert store.get("key") == "cached"
        assert store.get("key") == "cached"
        mock_consul.kv.get.assert_called_once()

    def test_get_returns_default_on_exception(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.get.side_effect = OSError("boom")
        assert store.get("key", default="def") == "def"

    def test_get_decodes_str_value(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.get.return_value = (1, {"Value": "already-str"})
        assert store.get("key") == "already-str"

    # ------------------------------------------------------------------
    # put
    # ------------------------------------------------------------------

    def test_put_success(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.put.return_value = True
        assert store.put("key", "val") is True
        mock_consul.kv.put.assert_called_once_with("key", "val")

    def test_put_clears_cache(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.get.return_value = (1, {"Value": b"old"})
        store.get("key")
        store.put("key", "new")
        assert "key" not in store._cache

    def test_put_failure_returns_false(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.put.side_effect = OSError("boom")
        assert store.put("key", "val") is False

    # ------------------------------------------------------------------
    # watch
    # ------------------------------------------------------------------

    def test_watch_calls_callback(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        calls: list[str] = []

        def cb(value: str) -> None:
            calls.append(value)

        mock_consul.kv.get.side_effect = [
            (1, {"Value": b"v1"}),
            (2, {"Value": b"v2"}),
            RuntimeError("stop"),
        ]

        t = threading.Thread(target=store.watch, args=("key", cb), daemon=True)
        t.start()
        t.join(timeout=1.0)
        assert not t.is_alive()
        assert calls == ["v1", "v2"]

    def test_watch_updates_cache(
        self, store: ConsulConfigStore, mock_consul: MagicMock
    ) -> None:
        mock_consul.kv.get.side_effect = [(1, {"Value": b"v1"}), RuntimeError("stop")]
        t = threading.Thread(target=store.watch, args=("key",), daemon=True)
        t.start()
        t.join(timeout=1.0)
        assert not t.is_alive()
        assert store._cache.get("key") == "v1"

    def test_watch_graceful_on_init_error(self, store: ConsulConfigStore) -> None:
        with patch("consul.Consul", side_effect=ImportError("no module")):
            store.watch("key")  # не бросает
