"""Tests для ``FallbackObjectStorage`` (S130 W3, FB-1 closure).

10+ tests покрывают:
- download: primary success, primary fail → secondary, both fail
- upload: primary success, primary fail → secondary
- delete: primary success, primary fail → secondary
- exists: primary success, primary fail → secondary
- list_keys: primary success, primary fail → secondary
- presigned_url: primary success, primary fail → secondary
- fallback_exceptions filter (specific exception types only)
- fallback_count per-method metric
- healthcheck: primary ok, primary fail → secondary
- supports_presigned
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.storage.fallback import FallbackObjectStorage


def _make_storage(
    *,
    download_return: bytes | None = None,
    download_raises: BaseException | None = None,
    upload_return: str | None = None,
    upload_raises: BaseException | None = None,
    delete_raises: BaseException | None = None,
    exists_return: bool | None = None,
    exists_raises: BaseException | None = None,
    list_return: list[str] | None = None,
    list_raises: BaseException | None = None,
    presigned_return: str | None = None,
    presigned_raises: BaseException | None = None,
    healthcheck_return: bool = True,
    healthcheck_raises: BaseException | None = None,
    supports_presigned: bool = True,
) -> Any:
    """Construct mock ObjectStorage с настраиваемым поведением.

    Для каждого метода: либо ``_return`` (success path), либо
    ``_raises`` (exception path). Если оба None — метод просто
    возвращает None.
    """
    s = MagicMock()
    s.supports_presigned = MagicMock(return_value=supports_presigned)

    # Helper: configure AsyncMock with either return_value or side_effect=Exception
    def _configure(
        mock: AsyncMock, return_value: Any, raises: BaseException | None
    ) -> None:
        if raises is not None:
            mock.side_effect = raises
        else:
            mock.return_value = return_value

    download_mock = AsyncMock()
    _configure(download_mock, download_return, download_raises)
    s.download = download_mock

    upload_mock = AsyncMock()
    _configure(upload_mock, upload_return, upload_raises)
    s.upload = upload_mock

    delete_mock = AsyncMock()
    if delete_raises is not None:
        delete_mock.side_effect = delete_raises
    else:
        delete_mock.return_value = None
    s.delete = delete_mock

    exists_mock = AsyncMock()
    _configure(exists_mock, exists_return, exists_raises)
    s.exists = exists_mock

    list_mock = AsyncMock()
    _configure(list_mock, list_return, list_raises)
    s.list_keys = list_mock

    presigned_mock = AsyncMock()
    _configure(presigned_mock, presigned_return, presigned_raises)
    s.presigned_url = presigned_mock

    healthcheck_mock = AsyncMock()
    _configure(healthcheck_mock, healthcheck_return, healthcheck_raises)
    s.healthcheck = healthcheck_mock
    return s


# === DOWNLOAD ===


@pytest.mark.asyncio
async def test_download_primary_success() -> None:
    """Primary returns data → no fallback."""
    primary = _make_storage(download_return=b"primary_data")
    secondary = _make_storage(download_return=b"secondary_data")
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.download("key1")
    assert result == b"primary_data"
    assert fb.fallback_count["download"] == 0
    secondary.download.assert_not_called()


@pytest.mark.asyncio
async def test_download_primary_fail_uses_secondary() -> None:
    """Primary raises → secondary called → returns secondary data."""
    primary = _make_storage(download_raises=ConnectionError("S3 unreachable"))
    secondary = _make_storage(download_return=b"secondary_data")
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.download("key1")
    assert result == b"secondary_data"
    assert fb.fallback_count["download"] == 1
    secondary.download.assert_awaited_once_with("key1")


@pytest.mark.asyncio
async def test_download_both_fail_raises_secondary_exc() -> None:
    """Both fail → propagates secondary exception."""
    primary = _make_storage(download_raises=ConnectionError("S3"))
    secondary = _make_storage(download_raises=OSError("FS"))
    fb = FallbackObjectStorage(primary, secondary)

    with pytest.raises(OSError, match="FS"):
        await fb.download("key1")
    assert fb.fallback_count["download"] == 1


# === UPLOAD ===


@pytest.mark.asyncio
async def test_upload_primary_success_no_fallback() -> None:
    primary = _make_storage(upload_return="s3://bucket/key1")
    secondary = _make_storage(upload_return="file:///var/key1")
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.upload("key1", b"data", "text/plain")
    assert result == "s3://bucket/key1"
    assert fb.fallback_count["upload"] == 0
    secondary.upload.assert_not_called()


@pytest.mark.asyncio
async def test_upload_primary_fail_uses_secondary() -> None:
    primary = _make_storage(upload_raises=ConnectionError("S3 503"))
    secondary = _make_storage(upload_return="file:///var/key1")
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.upload("key1", b"data", "text/plain")
    assert result == "file:///var/key1"
    assert fb.fallback_count["upload"] == 1
    secondary.upload.assert_awaited_once_with("key1", b"data", "text/plain")


# === DELETE ===


@pytest.mark.asyncio
async def test_delete_primary_success() -> None:
    primary = _make_storage()
    secondary = _make_storage()
    fb = FallbackObjectStorage(primary, secondary)

    await fb.delete("key1")
    primary.delete.assert_awaited_once_with("key1")
    secondary.delete.assert_not_called()
    assert fb.fallback_count["delete"] == 0


@pytest.mark.asyncio
async def test_delete_primary_fail_uses_secondary() -> None:
    primary = _make_storage(delete_raises=ConnectionError("S3"))
    secondary = _make_storage()
    fb = FallbackObjectStorage(primary, secondary)

    await fb.delete("key1")
    assert fb.fallback_count["delete"] == 1
    secondary.delete.assert_awaited_once_with("key1")


# === EXISTS ===


@pytest.mark.asyncio
async def test_exists_primary_success() -> None:
    primary = _make_storage(exists_return=True)
    secondary = _make_storage(exists_return=False)
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.exists("key1")
    assert result is True
    assert fb.fallback_count["exists"] == 0
    secondary.exists.assert_not_called()


@pytest.mark.asyncio
async def test_exists_primary_fail_uses_secondary() -> None:
    primary = _make_storage(exists_raises=ConnectionError("S3"))
    secondary = _make_storage(exists_return=True)
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.exists("key1")
    assert result is True
    assert fb.fallback_count["exists"] == 1


# === LIST_KEYS ===


@pytest.mark.asyncio
async def test_list_keys_primary_fail_uses_secondary() -> None:
    primary = _make_storage(list_raises=ConnectionError("S3"))
    secondary = _make_storage(list_return=["a", "b", "c"])
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.list_keys("prefix/")
    assert result == ["a", "b", "c"]
    assert fb.fallback_count["list_keys"] == 1


# === PRESIGNED_URL ===


@pytest.mark.asyncio
async def test_presigned_url_primary_fail_uses_secondary() -> None:
    primary = _make_storage(presigned_raises=ConnectionError("S3"))
    secondary = _make_storage(presigned_return="file:///var/key1")
    fb = FallbackObjectStorage(primary, secondary)

    result = await fb.presigned_url("key1", 7200)
    assert result == "file:///var/key1"
    assert fb.fallback_count["presigned_url"] == 1


# === FALLBACK_EXCEPTIONS FILTER ===


@pytest.mark.asyncio
async def test_fallback_exceptions_filter_excludes_keyerror() -> None:
    """KeyError от primary НЕ триггерит fallback (логическая ошибка, не network)."""
    primary = _make_storage(download_raises=KeyError("missing"))
    secondary = _make_storage(download_return=b"should_not_be_used")
    fb = FallbackObjectStorage(
        primary, secondary, fallback_exceptions=(ConnectionError, OSError)
    )

    with pytest.raises(KeyError):
        await fb.download("key1")
    assert fb.fallback_count["download"] == 0
    secondary.download.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_exceptions_filter_includes_connectionerror() -> None:
    """ConnectionError триггерит fallback при custom filter."""
    primary = _make_storage(download_raises=ConnectionError("S3"))
    secondary = _make_storage(download_return=b"sec")
    fb = FallbackObjectStorage(
        primary, secondary, fallback_exceptions=(ConnectionError,)
    )

    result = await fb.download("key1")
    assert result == b"sec"
    assert fb.fallback_count["download"] == 1


# === SUPPORTS_PRESIGNED / HEALTHCHECK ===


def test_supports_presigned_delegates_to_primary() -> None:
    primary = _make_storage(supports_presigned=False)
    secondary = _make_storage(supports_presigned=True)
    fb = FallbackObjectStorage(primary, secondary)
    assert fb.supports_presigned() is False


@pytest.mark.asyncio
async def test_healthcheck_primary_ok() -> None:
    primary = _make_storage(healthcheck_return=True)
    secondary = _make_storage(healthcheck_return=False)
    fb = FallbackObjectStorage(primary, secondary)
    assert await fb.healthcheck() is True


@pytest.mark.asyncio
async def test_healthcheck_primary_fail_secondary_ok() -> None:
    primary = _make_storage(healthcheck_raises=ConnectionError("S3"))
    secondary = _make_storage(healthcheck_return=True)
    fb = FallbackObjectStorage(primary, secondary)
    assert await fb.healthcheck() is True


# === METRICS / COUNT ===


@pytest.mark.asyncio
async def test_fallback_count_accumulates_across_calls() -> None:
    primary = _make_storage(download_raises=ConnectionError("S3"))
    secondary = _make_storage(download_return=b"data")
    fb = FallbackObjectStorage(primary, secondary)

    for _ in range(3):
        await fb.download("k")
    assert fb.fallback_count["download"] == 3
    # Other counters still 0
    assert fb.fallback_count["upload"] == 0
    assert fb.fallback_count["delete"] == 0
