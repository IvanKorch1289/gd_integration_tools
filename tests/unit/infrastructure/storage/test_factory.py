"""Unit-tests for storage factory (Wave F.5a/b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.config.validator._helpers import (
    ConfigSeverity,
    ProductionConfigError,
)
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


# Sprint 3.2: composition root fail-stop при APP_ENVIRONMENT=production.
# Вложенный класс ``app.environment`` поверх существующих стабов
# (``_FakeSettings*``) — паттерн ``class.app.environment = "..."``
# используется в Settings.app из pydantic.


class _FakeSettingsProdLocal:
    class app:
        environment = "production"

    class storage:
        local_storage_path = "/tmp/fake_storage_prod"
        provider = "local"


class _FakeSettingsProdS3:
    class app:
        environment = "production"

    class storage:
        local_storage_path = None
        provider = "s3"


def test_get_local_fs_storage_uses_settings_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettings(), raising=False,
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
        "src.backend.core.config.settings.settings", object(), raising=False,
    )
    get_local_fs_storage.cache_clear()
    storage = get_local_fs_storage()
    assert isinstance(storage, LocalFSStorage)
    assert storage._base == Path("var/storage").resolve()


def test_get_object_storage_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettings(), raising=False,
    )
    get_object_storage.cache_clear()
    storage = get_object_storage()
    assert isinstance(storage, LocalFSStorage)


def test_get_object_storage_non_local_fallback_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
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
        "src.backend.core.config.settings.settings", _FakeSettingsS3(), raising=False,
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
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
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
        "src.backend.core.config.settings.settings", _FakeSettingsS3(), raising=False,
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
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
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
        "src.backend.core.config.settings.settings", _FakeSettingsS3(), raising=False,
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


# === Sprint 3.2: composition root fail-stop при APP_ENVIRONMENT=production ===
# (L7 Infra completion). Production-check переехал из ``LocalFSStorage.__init__``
# (runtime warning) в ``factory._enforce_local_fs_safe_in_prod`` (fail-stop
# ``ProductionConfigError`` — RuntimeError-subclass с явным ConfigViolation).


def test_get_local_fs_storage_raises_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 3.2: ``get_local_fs_storage()`` поднимает ``ProductionConfigError``
    в production-окружении.

    Composition root fail-stop: вместо ``warnings.warn`` в ``__init__``
    (которое оператор мог пропустить) — явный ``RuntimeError``-subclass
    с ``ConfigViolation(severity=CRITICAL)``. Guard срабатывает до
    инстанциирования ``LocalFSStorage``.
    """
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings",
        _FakeSettingsProdLocal(),
        raising=False,
    )
    get_local_fs_storage.cache_clear()

    with pytest.raises(ProductionConfigError) as excinfo:
        get_local_fs_storage()

    # Проверяем, что ошибка несёт CRITICAL violation с понятным кодом.
    violations = excinfo.value.violations
    assert len(violations) == 1
    v = violations[0]
    assert v.severity == ConfigSeverity.CRITICAL
    assert v.code == "storage.local_in_prod"
    assert v.field == "storage.provider"
    assert v.context.get("environment") == "production"
    assert v.context.get("provider") == "local"


def test_get_local_fs_storage_succeeds_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 3.2: guard — no-op в development (sanity test).

    Без этого guard'а dev-окружение падало бы на каждом старте.
    """
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettings(), raising=False
    )
    get_local_fs_storage.cache_clear()

    storage = get_local_fs_storage()
    assert isinstance(storage, LocalFSStorage)


def test_get_object_storage_raises_in_production_when_provider_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 3.2: ``get_object_storage()`` поднимает ``ProductionConfigError``
    при ``provider='local'`` в production.

    Проверяет, что guard работает через публичный API
    :func:`get_object_storage` (composition root вызывает именно его
    из ``service_setup._register_storage_facade``).
    """
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings",
        _FakeSettingsProdLocal(),
        raising=False,
    )
    get_object_storage.cache_clear()
    get_local_fs_storage.cache_clear()

    with pytest.raises(ProductionConfigError) as excinfo:
        get_object_storage()

    assert excinfo.value.violations[0].code == "storage.local_in_prod"


def test_get_object_storage_raises_in_production_when_s3_fallback_to_local(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Sprint 3.2: ``provider='s3'`` + init failure в production → fail-stop
    (а НЕ silent fallback на LocalFS).

    Production-окружение не должно маскировать misconfiguration через
    silent fallback на unsafe LocalFS — guard срабатывает в обоих
    fallback-путях (``ImportError`` и generic ``Exception``), потому что
    они оба зовут ``get_local_fs_storage()`` (он и триггерит guard).
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
        "src.backend.core.config.settings.settings",
        _FakeSettingsProdS3(),
        raising=False,
    )
    get_object_storage.cache_clear()
    get_local_fs_storage.cache_clear()

    with caplog.at_level("WARNING"):
        with pytest.raises(ProductionConfigError) as excinfo:
            get_object_storage()

    # Guard должен сработать ДО того, как fallback успеет вернуть bare LocalFS.
    assert excinfo.value.violations[0].code == "storage.local_in_prod"
    # Warning о fallback'е логируется, но не приводит к silent-success.
    assert "S3ObjectStorage init failed" in caplog.text


def test_get_object_storage_raises_in_production_when_s3_success_with_local_secondary(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Sprint 3.2: ``provider='s3'`` + aioboto3 init success в production →
    fail-stop (НЕ FallbackObjectStorage с unsafe LocalFS secondary).

    Production-окружение не должно собирать chain S3→LocalFS — даже
    как fallback, потому что LocalFS сам по себе небезопасен. Guard
    срабатывает явно перед :class:`FallbackObjectStorage` обёрткой.
    """
    import sys
    import types

    from src.backend.infrastructure.storage.fallback import FallbackObjectStorage

    class _FakeS3ObjectStorage:
        def __init__(self, settings: object) -> None:
            self._settings = settings

    fake_s3 = types.ModuleType("src.backend.infrastructure.storage.s3")
    fake_s3.S3ObjectStorage = _FakeS3ObjectStorage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.backend.infrastructure.storage.s3", fake_s3)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings",
        _FakeSettingsProdS3(),
        raising=False,
    )
    get_object_storage.cache_clear()
    get_local_fs_storage.cache_clear()

    with caplog.at_level("INFO"):
        with pytest.raises(ProductionConfigError) as excinfo:
            get_object_storage()

    assert excinfo.value.violations[0].code == "storage.local_in_prod"
    # Wrapper НЕ должен быть собран — guard срабатывает раньше.
    # Sanity: FallbackObjectStorage импортирован, чтобы guard был
    # триггерирован ДО попытки его инстанциировать.
    assert FallbackObjectStorage is not None
