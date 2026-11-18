# ruff: noqa: S101
"""Регресс-тесты reference-роутов ``routes/`` (волна 34).

Роуты — декларативные манифесты + DSL-спеки; они реально загружаются
``RouteLoader``'ом на старте (``v11.route_loader_enabled`` — default ON).
Регрессы ниже фиксируют инварианты, которые молча нарушались.

Инвариант composition (extends + include)
-----------------------------------------
``routes/composition_demo`` демонстрирует обе возможности композиции.
Резолвер ``_resolve_include_extends`` обрабатывает ``extends:`` первым и
при слиянии отбрасывает ключ ``include`` — спека с обоими ключами теряла
``include`` молча, и ``shared_steps.yaml`` не попадал в pipeline вообще.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.backend.dsl.yaml_loader.resolve import _resolve_include_extends

_ROUTES_DIR = Path(__file__).resolve().parents[3] / "routes"


def _resolve(route: str, spec_name: str) -> dict[str, Any]:
    """Разрешить composition-спеку роута (extends/include)."""
    path = _ROUTES_DIR / route / spec_name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return _resolve_include_extends(dict(data), path.parent)


def _step_types(spec: dict[str, Any]) -> list[str]:
    """Список типов шагов разрешённой спеки."""
    steps = spec.get("steps") or []
    return [next(iter(step)) for step in steps if isinstance(step, dict)]


def test_composition_demo_includes_shared_steps() -> None:
    """``include:`` роута действительно подключает shared-шаги.

    Регресс: при ``extends:`` и ``include:`` в одном файле ключ ``include``
    терялся при слиянии — в pipeline попадали только audit-шаги, а
    ``set_property`` из ``shared_steps.yaml`` отсутствовали.
    """
    spec = _resolve("composition_demo", "main.dsl.yaml")
    types = _step_types(spec)
    assert "set_property" in types, (
        f"shared_steps.yaml не попал в pipeline composition_demo: {types}"
    )
    assert types.count("audit") >= 4, types


def test_composition_demo_pipelines_load() -> None:
    """Все pipeline-файлы роутов собираются в ``Pipeline`` без ошибок."""
    from src.backend.dsl.yaml_loader import load_pipeline_from_file

    for route_dir in sorted(_ROUTES_DIR.iterdir()):
        if not route_dir.is_dir():
            continue
        manifest_path = route_dir / "route.toml"
        if not manifest_path.is_file():
            continue
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))["route"]
        for spec_name in manifest.get("pipelines") or []:
            spec_path = route_dir / spec_name
            assert spec_path.is_file(), f"{spec_path} не найден"
            pipeline = load_pipeline_from_file(
                spec_path, default_route_id=manifest["name"]
            )
            assert pipeline.route_id


@pytest.mark.parametrize(
    "route",
    [
        "composition_demo",
        "echo_demo",
        "health_proxy_demo",
        "hello_route",
        "jupyter_hub_run",
        "osint_agent",
        "test_route_w1",
    ],
)
def test_route_manifest_declares_net_inbound(route: str) -> None:
    """Каждый DSL-роут объявляет ``net.inbound`` (ADR-0430)."""
    manifest_path = _ROUTES_DIR / route / "route.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))["route"]
    declared = {
        cap["name"] if isinstance(cap, dict) else str(cap).split(":", 1)[0]
        for cap in manifest.get("capabilities") or []
    }
    assert "net.inbound" in declared, f"{route}: не объявлено net.inbound"
