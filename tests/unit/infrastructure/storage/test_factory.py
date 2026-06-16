"""Unit-tests for storage factory (Wave F.5a/b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.storage.factory import (
    get_local_fs_storage,
    get_object_storage,
)
from src.backend.infrastructure.storage.local_fs import LocalFSStorage


class _FakeSettings:
    class storage:
        local_storage_path = "/tmp/fake_storage"
        provider = "local"


class _FakeSettingsS3:
    class storage:
        local_storage_path = None
        provider = "s3"


class _FakeSettingsNoStorage:
    pass


def test_get_local_fs_storage_uses_settings_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettings(), raising=False
    )
    # reset lru_cache
    get_local_fs_storage.cache_clear()
    storage = get_local_fs_storage()
    assert isinstance(storage, LocalFSStorage)
    assert storage._base == Path("/tmp/fake_storage")


def test_get_local_fs_storage_fallback_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", object(), raising=False
    )
    get_local_fs_storage.cache_clear()
    storage = get_local_fs_storage()
    assert isinstance(storage, LocalFSStorage)
    assert storage._base == Path("var/storage").resolve()


def test_get_object_storage_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettings(), raising=False
    )
    get_object_storage.cache_clear()
    storage = get_object_storage()
    assert isinstance(storage, LocalFSStorage)


def test_get_object_storage_non_local_fallback_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """S61 W1 regression: provider='s3' + missing aioboto3 → fallback на LocalFS.

    В dev-окружении aioboto3 установлен, поэтому ImportError нужно
    форсировать через monkeypatch на factory-импорт.
    """
    import builtins
    from typing import Any

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "src.backend.infrastructure.storage.s3":
            raise ImportError("forced for test (aioboto3 missing)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsS3(), raising=False
    )
    get_object_storage.cache_clear()
    with caplog.at_level("WARNING"):
        storage = get_object_storage()
    assert isinstance(storage, LocalFSStorage)
    assert "fallback" in caplog.text.lower() or "Wave 2.4" in caplog.text


def test_get_object_storage_exception_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings",
        _FakeSettingsNoStorage(),
        raising=False,
    )
    get_object_storage.cache_clear()
    storage = get_object_storage()
    assert isinstance(storage, LocalFSStorage)


# === S131 W1: FallbackObjectStorage wrapping in factory ===


class _FakeS3ObjectStorage:
    """Mock S3ObjectStorage для factory wrapper-теста."""

    def __init__(self, settings: object) -> None:
        self._settings = settings


def test_get_object_storage_s3_returns_fallback_wrapper(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """S131 W1: provider='s3' + aioboto3 available → FallbackObjectStorage(S3, LocalFS).

    Singleton (``lru_cache``) — wrapper переиспользуется между вызовами.
    """
    import sys
    import types

    from src.backend.infrastructure.storage.fallback import FallbackObjectStorage

    # Inject fake ``storage.s3`` module в sys.modules (botocore не установлен
    # в test env — реальный ``import s3`` фейлит, поэтому inject mock).
    fake_s3 = types.ModuleType("src.backend.infrastructure.storage.s3")
    fake_s3.S3ObjectStorage = _FakeS3ObjectStorage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.backend.infrastructure.storage.s3", fake_s3)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsS3(), raising=False
    )
    get_object_storage.cache_clear()
    get_local_fs_storage.cache_clear()

    with caplog.at_level("INFO"):
        storage = get_object_storage()

    # Wrapper, not bare S3
    assert isinstance(storage, FallbackObjectStorage), (
        f"expected FallbackObjectStorage, got {type(storage).__name__}"
    )
    # Primary = S3, Secondary = LocalFS
    assert isinstance(storage._primary, _FakeS3ObjectStorage)
    assert isinstance(storage._secondary, LocalFSStorage)
    # Chain name matches provider
    assert "s3" in storage._name
    # INFO log recorded
    assert "FallbackObjectStorage" in caplog.text or "minio chain" in caplog.text

    # Singleton: second call returns SAME instance (lru_cache)
    storage2 = get_object_storage()
    assert storage2 is storage


def test_get_object_storage_s3_init_failure_returns_bare_local(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """S131 W1: provider='s3' + S3 init raises Exception → bare LocalFS (НЕ wrapper).

    Pre-existing test ``test_get_object_storage_non_local_fallback_and_warns``
    покрывает ImportError path. Этот test — generic Exception path
    (e.g. aioboto3 credentials/network).
    """
    import sys
    import types

    class _BrokenS3ObjectStorage:
        def __init__(self, settings: object) -> None:
            raise RuntimeError("simulated S3 init failure (network/auth)")

    fake_s3 = types.ModuleType("src.backend.infrastructure.storage.s3")
    fake_s3.S3ObjectStorage = _BrokenS3ObjectStorage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.backend.infrastructure.storage.s3", fake_s3)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsS3(), raising=False
    )
    get_object_storage.cache_clear()
    get_local_fs_storage.cache_clear()

    with caplog.at_level("WARNING"):
        storage = get_object_storage()

    # Bare LocalFS, no wrapper
    assert isinstance(storage, LocalFSStorage), (
        f"expected bare LocalFSStorage on init failure, got {type(storage).__name__}"
    )
    assert "S3ObjectStorage init failed" in caplog.text
