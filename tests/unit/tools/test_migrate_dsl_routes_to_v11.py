# ruff: noqa: S101
"""Тесты tools/migrate_dsl_routes_to_v11.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

import migrate_dsl_routes_to_v11 as mod  # noqa: E402

from src.services.routes.manifest_v11 import load_route_manifest  # noqa: E402


def test_migrate_one_creates_dir_and_manifest(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "credit.yaml").write_text(
        "# pipeline\nfrom: rest\nto: db\n", encoding="utf-8"
    )
    routes = tmp_path / "routes"
    target, rendered = mod.migrate_one(
        legacy / "credit.yaml",
        routes,
        core_spec=">=0.2,<0.3",
        overwrite=False,
        dry_run=False,
    )
    assert target == routes / "credit"
    assert (target / "route.toml").is_file()
    assert (target / "pipeline.dsl.yaml").is_file()
    parsed = load_route_manifest(target / "route.toml")
    assert parsed.name == "credit"
    assert parsed.pipelines == ("pipeline.dsl.yaml",)
    assert parsed.requires_core == ">=0.2,<0.3"


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "x.yaml").write_text("# y\n", encoding="utf-8")
    routes = tmp_path / "routes"
    target, rendered = mod.migrate_one(
        legacy / "x.yaml", routes, core_spec=">=0.2,<0.3", overwrite=False, dry_run=True
    )
    assert not target.exists()
    assert 'name = "x"' in rendered


def test_overwrite_required(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "x.yaml").write_text("# y\n", encoding="utf-8")
    routes = tmp_path / "routes"
    routes.mkdir()
    (routes / "x").mkdir()
    with pytest.raises(FileExistsError):
        mod.migrate_one(
            legacy / "x.yaml", routes, core_spec=">=0.2", overwrite=False, dry_run=False
        )
    mod.migrate_one(
        legacy / "x.yaml", routes, core_spec=">=0.2", overwrite=True, dry_run=False
    )
    assert (routes / "x" / "route.toml").is_file()


def test_dsl_suffix_stripped(tmp_path: Path) -> None:
    """``credit.dsl.yaml`` → routes/credit/."""
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "credit.dsl.yaml").write_text("# y\n", encoding="utf-8")
    routes = tmp_path / "routes"
    target, _ = mod.migrate_one(
        legacy / "credit.dsl.yaml",
        routes,
        core_spec=">=0.2",
        overwrite=False,
        dry_run=False,
    )
    assert target == routes / "credit"


def test_main_directory_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "a.yaml").write_text("# a\n", encoding="utf-8")
    (legacy / "b.yaml").write_text("# b\n", encoding="utf-8")
    routes = tmp_path / "routes"
    rc = mod.main([str(legacy), str(routes)])
    assert rc == 0
    assert (routes / "a" / "route.toml").is_file()
    assert (routes / "b" / "route.toml").is_file()
    out = capsys.readouterr().out
    assert "MIGRATED" in out


def test_main_no_yaml_returns_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    routes = tmp_path / "routes"
    rc = mod.main([str(legacy), str(routes)])
    assert rc == 1


def test_missing_legacy_file(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    with pytest.raises(FileNotFoundError):
        mod.migrate_one(
            tmp_path / "absent.yaml",
            routes,
            core_spec=">=0.2",
            overwrite=False,
            dry_run=False,
        )
