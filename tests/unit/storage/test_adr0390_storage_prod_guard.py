"""ADR-0390 (волна 18, кластер G1) — prod-guard storage + tenant-префикс.

Дефекты:
* (1) critical: ``factory.get_object_storage()`` вызывал
  ``_enforce_local_fs_safe_in_prod()`` **безусловно** перед сборкой цепочки
  ``S3→LocalFS`` → ``ProductionConfigError`` даже при ``provider=aws``.
  В production storage не инициализировался ВООБЩЕ: все DSL-шаги
  ``to_s3``/``from_s3`` падали на старте.
* (11) medium: ``provider="local"`` возвращал bare ``LocalFSStorage`` —
  ключи без tenant-префикса, пер-тенантные квоты обходились.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from src.backend.core.config.validator._helpers import ProductionConfigError
from src.backend.infrastructure.storage import factory
from src.backend.infrastructure.storage.local_fs import LocalFSStorage
from src.backend.infrastructure.storage.tenant_wrapper import TenantObjectStorage


class _FakeS3:
    """Минимальный S3-backend для factory (без сети)."""

    def __init__(self, settings: object) -> None:
        self._settings = settings


class _FakeSettingsProd:
    """Settings-стаб: production + S3-провайдер."""

    class app:
        environment = "production"

    class storage:
        local_storage_path = None
        provider = "aws"


class _FakeSettingsProdLocal:
    """Settings-стаб: production + local-провайдер."""

    class app:
        environment = "production"

    class storage:
        local_storage_path = None
        provider = "local"


class _FakeSettingsDevLocal:
    """Settings-стаб: development + local-провайдер."""

    class app:
        environment = "development"

    class storage:
        local_storage_path = None
        provider = "local"


@pytest.fixture(autouse=True)
def _clear_factory_cache() -> Any:
    """Сбрасывает lru_cache фабрики между тестами."""
    factory.get_object_storage.cache_clear()
    factory.get_local_fs_storage.cache_clear()
    yield
    factory.get_object_storage.cache_clear()
    factory.get_local_fs_storage.cache_clear()


def _install_fake_s3(monkeypatch: pytest.MonkeyPatch, cls: type = _FakeS3) -> None:
    """Подменяет модуль ``storage.s3`` на заглушку (botocore нет в CI)."""
    fake_s3 = types.ModuleType("src.backend.infrastructure.storage.s3")
    fake_s3.S3ObjectStorage = cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.backend.infrastructure.storage.s3", fake_s3)


def test_prod_with_aws_provider_initializes_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(1) prod + provider=aws → storage инициализируется (без исключения)."""
    _install_fake_s3(monkeypatch)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsProd(), raising=False
    )

    storage = factory.get_object_storage()

    assert storage is not None
    assert isinstance(storage, TenantObjectStorage)


def test_prod_with_aws_provider_builds_s3_to_localfs_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(1) В production собирается цепочка S3 → LocalFS (LocalFS — secondary)."""
    from src.backend.infrastructure.storage.fallback import FallbackObjectStorage

    _install_fake_s3(monkeypatch)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsProd(), raising=False
    )

    chain = factory.get_object_storage().wrapped

    assert isinstance(chain, FallbackObjectStorage)
    assert isinstance(chain._primary, _FakeS3)
    assert isinstance(chain._secondary, LocalFSStorage)


def test_prod_with_local_provider_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(1) LocalFS как **фактический** backend в production → fail-stop."""
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings",
        _FakeSettingsProdLocal(),
        raising=False,
    )

    with pytest.raises(ProductionConfigError) as excinfo:
        factory.get_object_storage()

    assert excinfo.value.violations[0].code == "storage.local_in_prod"


def test_prod_with_broken_s3_fallback_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(1) Отказ S3 в production → LocalFS становится фактическим → fail-stop."""

    class _BrokenS3:
        def __init__(self, settings: object) -> None:
            raise RuntimeError("simulated S3 init failure")

    _install_fake_s3(monkeypatch, _BrokenS3)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _FakeSettingsProd(), raising=False
    )

    with pytest.raises(ProductionConfigError):
        factory.get_object_storage()


def test_local_provider_gets_tenant_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """(11) provider=local → tenant-обёртка (квоты нельзя обойти)."""
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings",
        _FakeSettingsDevLocal(),
        raising=False,
    )

    storage = factory.get_object_storage()

    assert isinstance(storage, TenantObjectStorage)
    assert isinstance(storage.wrapped, LocalFSStorage)


@pytest.mark.asyncio
async def test_local_provider_keys_are_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """(11) Ключ, записанный через local-storage, физически tenant-scoped."""
    from types import SimpleNamespace

    class _LocalSettings:
        class app:
            environment = "development"

        class storage:
            local_storage_path = str(tmp_path)
            provider = "local"

    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _LocalSettings(), raising=False
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.storage.tenant_wrapper.current_tenant",
        lambda: SimpleNamespace(tenant_id="bank_a"),
    )

    storage = factory.get_object_storage()
    await storage.upload("report.pdf", b"payload")

    # Файл лежит в tenant-каталоге (обход квот bare-ключом невозможен).
    assert (tmp_path / "tenants" / "bank_a" / "report.pdf").exists()
