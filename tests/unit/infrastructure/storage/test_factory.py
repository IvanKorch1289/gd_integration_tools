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


def test_get_local_fs_storage_uses_settings_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettings(), raising=False
    )
    # reset lru_cache
    get_local_fs_storage.cache_clear()
    storage = get_local_fs_storage()
    assert isinstance(storage, LocalFSStorage)
    assert storage._base == Path("/tmp/fake_storage")


def test_get_local_fs_storage_fallback_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", object(), raising=False
    )
    get_local_fs_storage.cache_clear()
    storage = get_local_fs_storage()
    assert isinstance(storage, LocalFSStorage)
    assert storage._base == Path("var/storage")


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
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsS3(), raising=False
    )
    get_object_storage.cache_clear()
    storage = get_object_storage()
    assert isinstance(storage, LocalFSStorage)
    assert "Wave 2.4" in caplog.text or "fallback" in caplog.text


def test_get_object_storage_exception_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsNoStorage(), raising=False
    )
    get_object_storage.cache_clear()
    storage = get_object_storage()
    assert isinstance(storage, LocalFSStorage)
