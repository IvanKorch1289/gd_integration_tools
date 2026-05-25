"""Unit-тесты для :class:`MemoryProtocol` (S24 W3 + S27 W3 backbone)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.interfaces.ai_memory import MemoryProtocol


class _FakeMemoryBackend:
    """Минимальный fake-backend, удовлетворяющий :class:`MemoryProtocol`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._store: dict[tuple[str, str], Any] = {}

    async def recall(
        self,
        namespace: str,
        query: str,
        *,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        self.calls.append(("recall", namespace, query, str(k)))
        items = [
            {"key": key, "value": value}
            for (ns, key), value in self._store.items()
            if ns == namespace and query in str(key)
        ]
        return items[:k]

    async def store(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl_s: int | None = None,
    ) -> None:
        self.calls.append(("store", namespace, key, str(ttl_s)))
        self._store[(namespace, key)] = value

    async def delete(
        self,
        namespace: str,
        key: str,
    ) -> None:
        self.calls.append(("delete", namespace, key))
        self._store.pop((namespace, key), None)


class _IncompleteBackend:
    """Backend без store / delete — не должен пройти isinstance."""

    async def recall(
        self,
        namespace: str,
        query: str,
        *,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        del namespace, query, k
        return []


def test_protocol_is_runtime_checkable() -> None:
    """MemoryProtocol должен быть :func:`runtime_checkable` Protocol."""
    backend = _FakeMemoryBackend()
    assert isinstance(backend, MemoryProtocol)


def test_protocol_rejects_incomplete_backend() -> None:
    """Backend без полного API не проходит isinstance-проверку."""
    incomplete = _IncompleteBackend()
    assert not isinstance(incomplete, MemoryProtocol)


def test_protocol_declares_three_methods() -> None:
    """Protocol должен декларировать ``recall`` / ``store`` / ``delete``."""
    for method in ("recall", "store", "delete"):
        assert hasattr(MemoryProtocol, method), f"Missing: {method}"


@pytest.mark.asyncio
async def test_fake_backend_store_recall_delete_roundtrip() -> None:
    """Round-trip: store → recall → delete на fake backend."""
    backend = _FakeMemoryBackend()
    await backend.store("acme:chat", "msg_1", {"text": "привет"}, ttl_s=60)
    found = await backend.recall("acme:chat", "msg", k=10)
    assert len(found) == 1
    assert found[0]["key"] == "msg_1"

    await backend.delete("acme:chat", "msg_1")
    after_delete = await backend.recall("acme:chat", "msg", k=10)
    assert after_delete == []


@pytest.mark.asyncio
async def test_recall_namespace_isolation() -> None:
    """Backend должен изолировать данные по namespace."""
    backend = _FakeMemoryBackend()
    await backend.store("tenant_a:chat", "k1", "value_a")
    await backend.store("tenant_b:chat", "k1", "value_b")

    a_results = await backend.recall("tenant_a:chat", "k1", k=10)
    b_results = await backend.recall("tenant_b:chat", "k1", k=10)
    assert len(a_results) == 1 and a_results[0]["value"] == "value_a"
    assert len(b_results) == 1 and b_results[0]["value"] == "value_b"
