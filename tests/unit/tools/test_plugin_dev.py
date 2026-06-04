"""Unit-тесты для plugin-dev mode launcher (S10 K5 W4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[3] / "tools" / "plugin_dev.py"
    spec = importlib.util.spec_from_file_location("_plugin_dev_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_compose_file_exists() -> None:
    assert mod.COMPOSE_FILE.is_file()


def test_compose_file_has_postgres_redis_mocks3() -> None:
    text = mod.COMPOSE_FILE.read_text(encoding="utf-8")
    assert "postgres:" in text
    assert "redis:" in text
    assert "mock-s3:" in text


def test_ensure_extension_raises_for_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    import pytest

    with pytest.raises(FileNotFoundError):
        mod._ensure_extension("nonexistent_xyz")


def test_ensure_extension_returns_path(monkeypatch, tmp_path) -> None:
    (tmp_path / "extensions" / "demo").mkdir(parents=True)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    p = mod._ensure_extension("demo")
    assert p.name == "demo"


def test_dry_run_prints_backend_command(capsys, tmp_path, monkeypatch) -> None:
    (tmp_path / "extensions" / "demo").mkdir(parents=True)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "COMPOSE_FILE", tmp_path / "docker-compose.plugin-dev.yml")
    rc = mod.main(["--name", "demo", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "backend:" in out
    assert "manage.py" in out
    assert "run" in out
