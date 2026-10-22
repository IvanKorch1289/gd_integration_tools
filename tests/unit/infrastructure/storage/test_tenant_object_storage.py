"""Tests для ``TenantObjectStorage`` (cycle 271 audit, CRITICAL-03).

До фикса все объекты всех тенантов попадали в один бакет под глобальным
``key_prefix="uploads"``: два тенанта, записавшие ``report.pdf``, делили один
ключ. Изоляция держалась только на дисциплине вызывающего (в ``orders`` ключ —
UUID), а не на механизме.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.storage.tenant_wrapper import (
    UNSCOPED_SEGMENT,
    TenantObjectStorage,
)

pytestmark = pytest.mark.asyncio


def _backend() -> MagicMock:
    b = MagicMock()
    b.upload = AsyncMock(return_value="s3://bucket/scoped/key")
    b.upload_stream = AsyncMock(return_value="s3://bucket/scoped/stream")
    b.download = AsyncMock(return_value=b"payload")
    b.delete = AsyncMock(return_value=None)
    b.exists = AsyncMock(return_value=True)
    b.list_keys = AsyncMock(return_value=[])
    b.presigned_url = AsyncMock(return_value="https://signed")
    b.supports_presigned = MagicMock(return_value=True)
    return b


def _provider(tenant_id: str | None):
    return lambda: (
        SimpleNamespace(tenant_id=tenant_id) if tenant_id else None
    )


async def test_keys_are_scoped_per_tenant() -> None:
    """Два тенанта с одним логическим ключом получают разные пути."""
    backend = _backend()
    a = TenantObjectStorage(backend, _provider("bank_a"))
    b = TenantObjectStorage(backend, _provider("bank_b"))

    await a.upload("report.pdf", b"x")
    await b.upload("report.pdf", b"x")

    assert backend.upload.await_args_list[0].args[0] == "tenants/bank_a/report.pdf"
    assert backend.upload.await_args_list[1].args[0] == "tenants/bank_b/report.pdf"


async def test_same_key_does_not_collide_across_tenants() -> None:
    """Ядро защиты: контент, записанный тенантом A, недоступен тенанту B."""
    store: dict[str, bytes] = {}

    backend = MagicMock()

    async def _upload(key: str, data: bytes, content_type: str | None = None) -> str:
        store[key] = data
        return key

    async def _download(key: str) -> bytes:
        if key not in store:
            raise FileNotFoundError(key)
        return store[key]

    backend.upload = AsyncMock(side_effect=_upload)
    backend.download = AsyncMock(side_effect=_download)

    a = TenantObjectStorage(backend, _provider("bank_a"))
    b = TenantObjectStorage(backend, _provider("bank_b"))

    await a.upload("secret.pdf", b"bank-a-private")
    await b.upload("secret.pdf", b"bank-b-private")

    assert await a.download("secret.pdf") == b"bank-a-private"
    assert await b.download("secret.pdf") == b"bank-b-private"


async def test_unscoped_objects_get_isolated_namespace() -> None:
    """Объекты вне tenant-контекста не смешиваются с tenant-объектами."""
    backend = _backend()
    system = TenantObjectStorage(backend, _provider(None))
    tenant = TenantObjectStorage(backend, _provider("bank_a"))

    await system.upload("health.json", b"{}")
    await tenant.upload("health.json", b"{}")

    assert (
        backend.upload.await_args_list[0].args[0]
        == f"tenants/{UNSCOPED_SEGMENT}/health.json"
    )
    assert backend.upload.await_args_list[1].args[0] == "tenants/bank_a/health.json"


async def test_list_keys_strips_prefix_so_round_trip_is_stable() -> None:
    """list_keys возвращает tenant-free пути — повторный download не удвоит."""
    backend = _backend()
    backend.list_keys = AsyncMock(
        return_value=["tenants/bank_a/a.bin", "tenants/bank_a/nested/b.bin"]
    )
    storage = TenantObjectStorage(backend, _provider("bank_a"))

    keys = await storage.list_keys()

    assert keys == ["a.bin", "nested/b.bin"]
    assert backend.list_keys.await_args.args[0] == "tenants/bank_a/"


async def test_download_after_list_keys_does_not_double_prefix() -> None:
    """Регрессия на «удвоение сегмента» при round-trip."""
    backend = _backend()
    backend.list_keys = AsyncMock(return_value=["tenants/bank_a/x.bin"])
    storage = TenantObjectStorage(backend, _provider("bank_a"))

    key = (await storage.list_keys())[0]
    await storage.download(key)

    assert backend.download.await_args.args[0] == "tenants/bank_a/x.bin"


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        ("download", "tenants/bank_a/k.bin"),
        ("delete", "tenants/bank_a/k.bin"),
        ("exists", "tenants/bank_a/k.bin"),
        ("presigned_url", "tenants/bank_a/k.bin"),
    ],
)
async def test_read_and_delete_ops_are_scoped(
    call: str, expected: str
) -> None:
    """Ни одна операция не должна обходить tenant-префикс."""
    backend = _backend()
    storage = TenantObjectStorage(backend, _provider("bank_a"))

    if call == "presigned_url":
        await storage.presigned_url("k.bin")
    else:
        await getattr(storage, call)("k.bin")

    method = backend.presigned_url if call == "presigned_url" else getattr(backend, call)
    assert method.await_args.args[0] == expected


async def test_upload_stream_is_scoped() -> None:
    """Stream-upload тоже обязан получить префикс — иначе обход тривиален."""

    async def _gen():
        yield b"chunk"

    backend = _backend()
    storage = TenantObjectStorage(backend, _provider("bank_a"))

    await storage.upload_stream("big.bin", _gen())

    assert backend.upload_stream.await_args.args[0] == "tenants/bank_a/big.bin"


async def test_supports_presigned_delegates() -> None:
    backend = _backend()
    storage = TenantObjectStorage(backend, _provider("bank_a"))
    assert storage.supports_presigned() is True
