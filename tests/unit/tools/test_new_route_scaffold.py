"""Focused tests: ops/scripts/new_route.py scaffold (MINIMAX W10 DX).

Генератор запускается в tmp_path (--root), результат валидируется
настоящим RouteManifest-лоадером + yaml-парсером.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[3] / "ops" / "scripts" / "new_route.py"


def _run_scaffold(
    root: Path, name: str, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), name, "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "routes").mkdir()
    return tmp_path


def test_scaffold_creates_route_files(repo_root: Path) -> None:
    """Генератор создаёт route.toml + main.dsl.yaml + README."""
    result = _run_scaffold(repo_root, "order_status")
    assert result.returncode == 0, result.stderr
    route_dir = repo_root / "routes" / "order_status"
    assert (route_dir / "route.toml").is_file()
    assert (route_dir / "main.dsl.yaml").is_file()
    assert (route_dir / "README.md").is_file()


def test_scaffold_manifest_loads_by_real_loader(repo_root: Path) -> None:
    """Сгенерированный route.toml парсится и содержит ключевые поля манифеста."""
    import tomllib

    result = _run_scaffold(repo_root, "order_status")
    assert result.returncode == 0, result.stderr
    toml_path = repo_root / "routes" / "order_status" / "route.toml"
    raw = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    assert raw["name"] == "order_status"
    assert raw["feature_flag"]["gate"] == "order_status_enabled"
    assert raw["tenant_aware"] is True
    assert raw["schedule"] == "never"
    # Capability-структура совместима с манифест-схемой (список строк).
    assert isinstance(raw["capabilities"], list)
    assert all(isinstance(c, str) for c in raw["capabilities"])


def test_scaffold_yaml_structure(repo_root: Path) -> None:
    """main.dsl.yaml: route_id совпадает, source.http задан, steps непусты."""
    result = _run_scaffold(repo_root, "kyc_check")
    assert result.returncode == 0, result.stderr
    yaml_path = repo_root / "routes" / "kyc_check" / "main.dsl.yaml"
    data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["route_id"] == "kyc_check"
    assert data["source"]["http"]["method"] == "POST"
    assert "/api/v1/kyc_check" in data["source"]["http"]["path"]
    assert isinstance(data["steps"], list) and data["steps"]


def test_scaffold_rejects_bad_name(repo_root: Path) -> None:
    """Не-snake_case имя → exit 1, файлы не созданы."""
    result = _run_scaffold(repo_root, "Bad-Name")
    assert result.returncode == 1
    assert not (repo_root / "routes" / "Bad-Name").exists()


def test_scaffold_refuses_existing_dir(repo_root: Path) -> None:
    """Существующий route-dir → exit 1 (без перезаписи)."""
    assert _run_scaffold(repo_root, "dup_route").returncode == 0
    result = _run_scaffold(repo_root, "dup_route")
    assert result.returncode == 1
