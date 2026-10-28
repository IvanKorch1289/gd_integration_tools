"""Unit-тесты StorageFacade (S133 W4).

Покрытие:
    * делегация в ObjectStorage;
    * capability check для read/write;
    * оборачивание ошибок в ServiceError.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.security.capabilities import CapabilityDeniedError
from src.backend.services.storage.facade import StorageFacade


class _FakeStorage(ObjectStorage):
    """Фейковый ObjectStorage для тестов."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._store: dict[str, bytes] = {}

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        self.calls.append({"op": "upload", "key": key, "content_type": content_type})
        self._store[key] = data
        return f"loc://{key}"

    async def download(self, key: str) -> bytes:
        self.calls.append({"op": "download", "key": key})
        if key not in self._store:
            raise FileNotFoundError(key)
        return self._store[key]

    async def delete(self, key: str) -> None:
        self.calls.append({"op": "delete", "key": key})
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        self.calls.append({"op": "exists", "key": key})
        return key in self._store

    async def list_keys(self, prefix: str = "") -> list[str]:
        self.calls.append({"op": "list_keys", "prefix": prefix})
        return [k for k in self._store if k.startswith(prefix)]

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        self.calls.append({"op": "presigned_url", "key": key, "expires_in": expires_in})
        return f"http://example.com/{key}?expires={expires_in}"


@pytest.mark.asyncio
async def test_upload_delegates_and_checks_write_capability() -> None:
    """upload вызывает capability_check storage.write.<key>."""
    checks: list[tuple[str, str, str | None]] = []
    storage = _FakeStorage()
    facade = StorageFacade(
        storage=storage,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
        plugin="ext-1",
    )

    loc = await facade.upload(
        "docs/report.pdf", b"data", content_type="application/pdf"
    )

    assert loc == "loc://docs/report.pdf"
    assert checks == [("ext-1", "storage.write", "docs/report.pdf")]
    assert storage.calls[0]["op"] == "upload"


@pytest.mark.asyncio
async def test_download_delegates_and_checks_read_capability() -> None:
    """download вызывает capability_check storage.read.<key>."""
    checks: list[tuple[str, str, str | None]] = []
    storage = _FakeStorage()
    await storage.upload("docs/report.pdf", b"data")
    facade = StorageFacade(
        storage=storage,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
        plugin="ext-1",
    )

    data = await facade.download("docs/report.pdf")

    assert data == b"data"
    assert checks == [("ext-1", "storage.read", "docs/report.pdf")]


@pytest.mark.asyncio
async def test_list_keys_uses_read_capability_with_prefix_scope() -> None:
    """list_keys проверяет storage.read.<prefix>."""
    checks: list[tuple[str, str, str | None]] = []
    storage = _FakeStorage()
    await storage.upload("a/1.txt", b"1")
    await storage.upload("a/2.txt", b"2")
    facade = StorageFacade(
        storage=storage,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
        plugin="ext-1",
    )

    keys = await facade.list_keys("a/")

    assert set(keys) == {"a/1.txt", "a/2.txt"}
    assert checks == [("ext-1", "storage.read", "a/")]


@pytest.mark.asyncio
async def test_delete_uses_write_capability() -> None:
    """delete проверяет storage.write.<key>."""
    checks: list[tuple[str, str, str | None]] = []
    storage = _FakeStorage()
    await storage.upload("k", b"v")
    facade = StorageFacade(
        storage=storage,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
        plugin="ext-1",
    )

    await facade.delete("k")

    assert checks == [("ext-1", "storage.write", "k")]


@pytest.mark.asyncio
async def test_presigned_url_requires_presign_capability() -> None:
    """presigned_url проверяет storage.presign.<key> (а не storage.read).

    Presigned-URL даёт клиенту прямую ссылку на бакет → это отдельная
    capability, а не чтение.
    """
    checks: list[tuple[str, str, str | None]] = []
    storage = _FakeStorage()
    facade = StorageFacade(
        storage=storage,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
        plugin="ext-1",
    )

    url = await facade.presigned_url("docs/report.pdf", expires_in=60)

    assert url == "http://example.com/docs/report.pdf?expires=60"
    assert checks == [("ext-1", "storage.presign", "docs/report.pdf")]


@pytest.mark.asyncio
async def test_presigned_url_grants_only_presign_capability() -> None:
    """Grant по storage.read не покрывает presign — нужен именно storage.presign."""

    def _check(plugin: str, cap: str, scope: str | None) -> None:
        if cap != "storage.presign":
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=cap,
                requested_scope=scope,
                declared_scope=None,
            )

    storage = _FakeStorage()
    facade = StorageFacade(storage=storage, capability_check=_check, plugin="ext-1")

    url = await facade.presigned_url("docs/report.pdf")

    assert url.startswith("http://example.com/docs/report.pdf")


@pytest.mark.asyncio
async def test_presigned_url_denied_when_presign_not_declared() -> None:
    """Без storage.presign — CapabilityDeniedError, backend не вызывается."""

    def _check(plugin: str, cap: str, scope: str | None) -> None:
        raise CapabilityDeniedError(
            plugin=plugin, capability=cap, requested_scope=scope, declared_scope=None
        )

    storage = _FakeStorage()
    facade = StorageFacade(storage=storage, capability_check=_check, plugin="ext-1")

    with pytest.raises(CapabilityDeniedError):
        await facade.presigned_url("docs/report.pdf")
    assert storage.calls == []


class _NoPresignStorage(_FakeStorage):
    """Backend, который не умеет выдавать presigned-URL."""

    def supports_presigned(self) -> bool:
        """Presigned-URL не поддерживается."""
        return False


class _LegacyStorage:
    """Backend без метода ``supports_presigned`` (old implementation).

    Capability-нейтральный feature-флаг: фасад обязан вернуть default
    ``True``, а не падать с ``AttributeError``.
    """


def test_supports_presigned_defaults_true_without_backend_support() -> None:
    """Backend без ``supports_presigned`` → ``True`` (default, как в fallback)."""
    facade = StorageFacade(storage=_LegacyStorage())  # type: ignore[arg-type]

    assert facade.supports_presigned() is True


def test_supports_presigned_delegates_to_backend() -> None:
    """Фасад делегирует ``supports_presigned()`` backend'у."""
    facade = StorageFacade(storage=_NoPresignStorage(), plugin="ext-1")

    assert facade.supports_presigned() is False


def test_supports_presigned_requires_no_capability() -> None:
    """Feature-флаг не требует capability — только чтение данных требует."""

    def _check(plugin: str, cap: str, scope: str | None) -> None:
        raise CapabilityDeniedError(
            plugin=plugin, capability=cap, requested_scope=scope, declared_scope=None
        )

    facade = StorageFacade(storage=_NoPresignStorage(), capability_check=_check)

    assert facade.supports_presigned() is False


@pytest.mark.asyncio
async def test_backend_error_wrapped_in_service_error() -> None:
    """Ошибка backend'а оборачивается в ServiceError."""
    storage = _FakeStorage()
    storage.download = AsyncMock(side_effect=RuntimeError("s3 down"))
    facade = StorageFacade(storage=storage, plugin="ext-1")

    with pytest.raises(ServiceError, match="s3 down"):
        await facade.download("k")


@pytest.mark.asyncio
async def test_no_capability_check_skips_gate() -> None:
    """При отсутствии capability_check операции выполняются без gate."""
    storage = _FakeStorage()
    facade = StorageFacade(storage=storage, plugin="ext-1")

    await facade.upload("k", b"v")
    assert await facade.exists("k") is True
