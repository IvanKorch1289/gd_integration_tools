"""Unit-тесты для scaffold-route wizard (S10 K5 W2)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


def _load_module():
    path = Path(__file__).resolve().parents[3] / "tools" / "scaffold_route.py"
    spec = importlib.util.spec_from_file_location("_scaffold_route_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_build_dsl_yaml_minimal_route() -> None:
    text = mod.build_dsl_yaml(
        source="http", sink="http", ai=False, retry=False, name="demo"
    )
    data = yaml.safe_load(text)
    assert data["route_id"] == "demo"
    assert "http" in data["source"]
    # ожидаем как минимум call_function + sink + audit + to
    assert len(data["steps"]) >= 4


def test_build_dsl_yaml_with_ai_and_retry() -> None:
    text = mod.build_dsl_yaml(
        source="kafka", sink="db", ai=True, retry=True, name="demo"
    )
    data = yaml.safe_load(text)
    types = [next(iter(step.keys())) for step in data["steps"]]
    assert "policy" in types
    assert "llm_call" in types
    assert "crud_create" in types


def test_route_toml_contains_capabilities() -> None:
    text = mod.build_route_toml(name="x", ai=True)
    assert 'name = "x"' in text
    assert "ai.llm" in text
    assert "net.outbound" in text


def test_route_toml_without_ai_skips_capability() -> None:
    text = mod.build_route_toml(name="x", ai=False)
    assert "ai.llm" not in text


def test_write_scaffold_creates_files(tmp_path: Path) -> None:
    target = mod.write_scaffold(
        "demo_route",
        source="http",
        sink="http",
        ai=False,
        retry=False,
        force=False,
        routes_dir=tmp_path,
    )
    assert (target / "route.toml").is_file()
    assert (target / "main.dsl.yaml").is_file()
    # содержимое валидно
    data = yaml.safe_load((target / "main.dsl.yaml").read_text(encoding="utf-8"))
    assert data["route_id"] == "demo_route"


def test_write_scaffold_refuses_existing_dir_without_force(tmp_path: Path) -> None:
    mod.write_scaffold(
        "x",
        source="http",
        sink="http",
        ai=False,
        retry=False,
        force=False,
        routes_dir=tmp_path,
    )
    with pytest.raises(FileExistsError):
        mod.write_scaffold(
            "x",
            source="http",
            sink="http",
            ai=False,
            retry=False,
            force=False,
            routes_dir=tmp_path,
        )


def test_write_scaffold_force_overwrites(tmp_path: Path) -> None:
    mod.write_scaffold(
        "x",
        source="http",
        sink="http",
        ai=False,
        retry=False,
        force=False,
        routes_dir=tmp_path,
    )
    # второй вызов с force=True — должен пройти
    mod.write_scaffold(
        "x",
        source="http",
        sink="http",
        ai=False,
        retry=False,
        force=True,
        routes_dir=tmp_path,
    )
