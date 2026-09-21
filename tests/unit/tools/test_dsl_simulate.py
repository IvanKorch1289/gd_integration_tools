"""Тесты для dsl_simulate CLI (S10 K5 W3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[3] / "tools" / "dsl_simulate.py"
    spec = importlib.util.spec_from_file_location("_dsl_simulate_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_resolve_route_path_for_file(tmp_path: Path) -> None:
    f = tmp_path / "x.yaml"
    f.write_text("route_id: x\nsteps: []\n", encoding="utf-8")
    assert mod._resolve_route_path(str(f)) == f


def test_resolve_route_path_for_route_name_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "routes" / "my_route").mkdir(parents=True)
    (tmp_path / "routes" / "my_route" / "main.dsl.yaml").write_text(
        "route_id: my_route\nsteps: []\n", encoding="utf-8"
    )
    assert mod._resolve_route_path("my_route").name == "main.dsl.yaml"


def test_resolve_route_path_missing_raises() -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        mod._resolve_route_path("nonexistent_route_xyz")


def test_main_runs_dry_run_on_file(tmp_path: Path, monkeypatch, capsys) -> None:
    f = tmp_path / "demo.yaml"
    f.write_text(
        "route_id: demo\nsteps:\n  - call_function: { ref: m:f }\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    code = mod.main([str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Route:" in out
    assert "Waterfall:" in out


def test_main_json_format(tmp_path: Path, monkeypatch, capsys) -> None:
    import json as _json

    f = tmp_path / "demo.yaml"
    f.write_text("route_id: j\nsteps:\n  - audit: { action: ok }\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    mod.main([str(f), "--json"])
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data["route_id"] == "j"
    assert isinstance(data["steps"], list)
