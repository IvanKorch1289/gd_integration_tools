"""Unit-тесты ``MemoryCertBackend`` + ``CertStore`` (без БД).

Покрывает:

* ``MemoryCertBackend.save`` -> ``get`` round-trip;
* версия инкрементируется при повторном ``save``;
* ``history(service_id)`` возвращает все версии в порядке записи;
* ``list_expiring(deadline)`` фильтрует по дате;
* hot-cache фасад ``CertStore``: ``get`` использует кэш после ``set``;
* ``invalidate(service_id)`` сбрасывает локальный кэш;
* ``subscribe_updates`` -> подписчики получают ``service_id`` после ``set``.

Все listener-варианты проверяются: sync-callable и async-coroutine.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.config.cert_store import CertStoreSettings
from src.infrastructure.security.cert_store import (
    CertEntry,
    CertStore,
    MemoryCertBackend,
)

_TEST_PEM = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\n"
    "TEST-CERT-PAYLOAD-FOR-UNIT\n"
    "-----END CERTIFICATE-----\n"
)
_TEST_PEM_V2 = _TEST_PEM.replace("TEST-CERT-PAYLOAD-FOR-UNIT", "ROTATED-PAYLOAD-V2")


def _future(days: int = 365) -> datetime:
    """Возвращает datetime ``days`` дней в будущем (UTC)."""
    return datetime.now(tz=timezone.utc) + timedelta(days=days)


def _settings() -> CertStoreSettings:
    """``CertStoreSettings`` с in-memory backend для изолированных тестов."""
    return CertStoreSettings(backend="memory")


# ── MemoryCertBackend ──────────────────────────────────────────────────────


async def test_memory_save_then_get_roundtrip() -> None:
    """``save`` сохраняет запись, ``get`` возвращает её с теми же полями."""
    backend = MemoryCertBackend()
    expires = _future()

    saved = await backend.save("svc1", _TEST_PEM, expires, description="primary")

    assert isinstance(saved, CertEntry)
    fetched = await backend.get("svc1")
    assert fetched is not None
    assert fetched.service_id == "svc1"
    assert fetched.pem == _TEST_PEM
    assert fetched.fingerprint == saved.fingerprint
    assert fetched.expires_at == expires
    assert fetched.description == "primary"
    assert fetched.version == 1


async def test_memory_get_missing_returns_none() -> None:
    """``get`` несуществующего service_id возвращает ``None``."""
    backend = MemoryCertBackend()
    assert await backend.get("nope") is None


async def test_memory_save_increments_version() -> None:
    """Повторный ``save`` для того же ``service_id`` увеличивает ``version``."""
    backend = MemoryCertBackend()
    expires = _future()

    first = await backend.save("svc1", _TEST_PEM, expires)
    second = await backend.save("svc1", _TEST_PEM_V2, expires)

    assert first.version == 1
    assert second.version == 2
    current = await backend.get("svc1")
    assert current is not None
    assert current.version == 2
    assert current.pem == _TEST_PEM_V2


async def test_memory_history_returns_all_versions() -> None:
    """``history`` возвращает все версии для конкретного ``service_id``."""
    backend = MemoryCertBackend()
    expires = _future()

    await backend.save("svc1", _TEST_PEM, expires)
    await backend.save("svc1", _TEST_PEM_V2, expires)
    await backend.save("svc2", _TEST_PEM, expires)

    history = await backend.history("svc1")
    assert [e.version for e in history] == [1, 2]
    assert all(e.service_id == "svc1" for e in history)


async def test_memory_list_expiring_filters_by_deadline() -> None:
    """``list_expiring`` отдаёт только те записи, у которых ``expires_at <= deadline``."""
    backend = MemoryCertBackend()

    soon = _future(days=10)
    far = _future(days=400)
    await backend.save("soon", _TEST_PEM, soon)
    await backend.save("far", _TEST_PEM_V2, far)

    deadline = _future(days=30)
    expiring = await backend.list_expiring(deadline)
    ids = {e.service_id for e in expiring}
    assert ids == {"soon"}


# ── CertStore facade ───────────────────────────────────────────────────────


async def test_certstore_set_then_get_uses_hot_cache() -> None:
    """После ``set`` следующий ``get`` берёт значение из in-process cache."""
    store = CertStore(MemoryCertBackend(), _settings())
    expires = _future()

    await store.set("svc1", _TEST_PEM, expires)
    pem = await store.get("svc1")
    assert pem == _TEST_PEM

    # Подмена backend.get на падающий, чтобы убедиться, что cache hit
    async def _boom(_service_id: str) -> None:
        raise AssertionError("backend.get must not be called: cache hit expected")

    store._backend.get = _boom
    assert await store.get("svc1") == _TEST_PEM


async def test_certstore_get_entry_returns_full_record() -> None:
    """``get_entry`` возвращает ``CertEntry`` с метаданными."""
    store = CertStore(MemoryCertBackend(), _settings())
    expires = _future()
    await store.set("svc1", _TEST_PEM, expires, description="desc")

    entry = await store.get_entry("svc1")
    assert entry is not None
    assert entry.pem == _TEST_PEM
    assert entry.expires_at == expires
    assert entry.description == "desc"
    assert entry.version == 1


async def test_certstore_invalidate_drops_local_cache() -> None:
    """``invalidate`` сбрасывает кэш — следующий ``get`` идёт в backend."""
    backend = MemoryCertBackend()
    store = CertStore(backend, _settings())
    expires = _future()
    await store.set("svc1", _TEST_PEM, expires)

    calls = {"count": 0}
    original_get = backend.get

    async def _counting_get(service_id: str) -> CertEntry | None:
        calls["count"] += 1
        return await original_get(service_id)

    backend.get = _counting_get

    store.invalidate("svc1")
    await store.get("svc1")
    assert calls["count"] == 1


async def test_certstore_subscribe_updates_sync_listener() -> None:
    """Sync listener вызывается с ``service_id`` после ``set``."""
    store = CertStore(MemoryCertBackend(), _settings())
    received: list[str] = []
    store.subscribe_updates(lambda sid: received.append(sid))

    await store.set("svc1", _TEST_PEM, _future())

    assert received == ["svc1"]


async def test_certstore_subscribe_updates_async_listener() -> None:
    """Async listener (coroutine) дожидается завершения после ``set``."""
    store = CertStore(MemoryCertBackend(), _settings())
    received: list[str] = []

    async def _on_update(sid: str) -> None:
        received.append(sid)

    store.subscribe_updates(_on_update)
    await store.set("svc1", _TEST_PEM, _future())

    assert received == ["svc1"]


async def test_certstore_listener_failure_is_swallowed() -> None:
    """Падение одного listener'а не ломает остальных."""
    store = CertStore(MemoryCertBackend(), _settings())
    received: list[str] = []

    def _bad(_sid: str) -> None:
        raise RuntimeError("boom")

    store.subscribe_updates(_bad)
    store.subscribe_updates(lambda sid: received.append(sid))

    await store.set("svc1", _TEST_PEM, _future())
    assert received == ["svc1"]


async def test_certstore_get_expiring_soon_uses_settings_window() -> None:
    """``get_expiring_soon`` ограничен окном ``expire_warn_days`` из settings."""
    backend = MemoryCertBackend()
    settings = CertStoreSettings(backend="memory", expire_warn_days=7)
    store = CertStore(backend, settings)

    await store.set("close", _TEST_PEM, _future(days=3))
    await store.set("far", _TEST_PEM_V2, _future(days=90))

    expiring = await store.get_expiring_soon()
    ids = {e.service_id for e in expiring}
    assert ids == {"close"}


async def test_certstore_from_settings_memory_backend_factory() -> None:
    """``from_settings(backend='memory')`` собирает store с ``MemoryCertBackend``."""
    settings = CertStoreSettings(backend="memory")
    store = CertStore.from_settings(settings)
    assert isinstance(store._backend, MemoryCertBackend)

    pytest.importorskip("typing")  # просто чтобы тест не оставался "пустым"
    await store.set("svc1", _TEST_PEM, _future())
    assert await store.get("svc1") == _TEST_PEM
