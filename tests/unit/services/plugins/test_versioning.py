# ruff: noqa: S101
"""Sprint 14 K5 W2 — unit-тесты ``PluginVersionService``."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.services.plugins.versioning import (
    InstalledVersion,
    PluginVersionError,
    PluginVersionService,
    RollbackResult,
)


def _write_plugin(root: Path, *, version: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.toml").write_text(
        f'name = "demo"\n'
        f'version = "{version}"\n'
        f'requires_core = ">=0.2,<1.0"\n'
        f'entry_class = "extensions.demo.plugin.Demo"\n',
        encoding="utf-8",
    )


class FakeLoader:
    """Минимальная заглушка PluginLoaderProtocol для тестов."""

    @property
    def loaded(self) -> tuple:
        return ()

    async def shutdown_all(self) -> None:
        return None

    async def discover_and_load(self) -> tuple:
        return ()


@pytest.fixture()
def extensions_dir(tmp_path: Path) -> Path:
    return tmp_path / "extensions"


def test_list_versions_active_and_archived(extensions_dir: Path) -> None:
    active = extensions_dir / "demo"
    archived = extensions_dir / "demo.0.9.0"
    _write_plugin(active, version="1.0.0")
    _write_plugin(archived, version="0.9.0")

    svc = PluginVersionService(loader=FakeLoader(), extensions_dir=extensions_dir)
    versions = svc.list_versions("demo")

    assert any(v.version == "1.0.0" and v.is_active for v in versions)
    assert any(v.version == "0.9.0" and not v.is_active for v in versions)


def test_list_versions_returns_empty_for_unknown_plugin(extensions_dir: Path) -> None:
    extensions_dir.mkdir()
    svc = PluginVersionService(loader=FakeLoader(), extensions_dir=extensions_dir)
    assert svc.list_versions("absent") == []


def test_diff_two_versions(extensions_dir: Path) -> None:
    active = extensions_dir / "demo"
    archived = extensions_dir / "demo.0.9.0"
    _write_plugin(active, version="1.0.0")
    _write_plugin(archived, version="0.9.0")

    svc = PluginVersionService(loader=FakeLoader(), extensions_dir=extensions_dir)
    result = svc.diff("demo", from_version="0.9.0", to_version="1.0.0")

    assert result["plugin"] == "demo"
    assert result["from_version"] == "0.9.0"
    assert result["to_version"] == "1.0.0"
    assert "payload" in result


def test_diff_unknown_version_raises(extensions_dir: Path) -> None:
    active = extensions_dir / "demo"
    _write_plugin(active, version="1.0.0")

    svc = PluginVersionService(loader=FakeLoader(), extensions_dir=extensions_dir)
    with pytest.raises(PluginVersionError, match="not found"):
        svc.diff("demo", from_version="0.5.0", to_version="1.0.0")


@pytest.mark.asyncio
async def test_rollback_noop_when_same_version(extensions_dir: Path) -> None:
    active = extensions_dir / "demo"
    _write_plugin(active, version="1.0.0")
    _write_plugin(extensions_dir / "demo.1.0.0", version="1.0.0")  # backup

    svc = PluginVersionService(loader=FakeLoader(), extensions_dir=extensions_dir)
    result = await svc.rollback("demo", to_version="1.0.0")

    assert isinstance(result, RollbackResult)
    assert result.status == "noop"


@pytest.mark.asyncio
async def test_rollback_unknown_version_raises(extensions_dir: Path) -> None:
    active = extensions_dir / "demo"
    _write_plugin(active, version="1.0.0")

    svc = PluginVersionService(loader=FakeLoader(), extensions_dir=extensions_dir)
    with pytest.raises(PluginVersionError, match="snapshot not found"):
        await svc.rollback("demo", to_version="2.0.0")


def test_installed_version_to_dict() -> None:
    iv = InstalledVersion(
        plugin="demo", version="1.0.0", path=Path("/tmp/demo"), is_active=True
    )
    payload = iv.to_dict()
    assert payload == {
        "plugin": "demo",
        "version": "1.0.0",
        "path": "/tmp/demo",
        "is_active": True,
    }
