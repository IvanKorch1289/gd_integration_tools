"""Smoke-тесты для discovery reference routes (ADR-0056, V11.1a).

Проверяют, что манифесты route.toml и DSL-файлы *.dsl.yaml
корректно загружаются стандартными парсерами без ошибок.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

# Корень проекта — три уровня вверх от этого файла (tests/unit/dsl/route/)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent


def _routes_root() -> Path:
    """Возвращает абсолютный путь к директории routes/ проекта."""
    return _PROJECT_ROOT / "routes"


class TestHealthProxyDemoRoute:
    """Smoke-тесты для reference route health_proxy_demo."""

    def test_routes_toml_loadable(self) -> None:
        """route.toml для health_proxy_demo должен загружаться без ошибок."""
        toml_path = _routes_root() / "health_proxy_demo" / "route.toml"
        assert toml_path.exists(), f"Файл не найден: {toml_path}"
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
        assert "route" in data, "Секция [route] обязательна в route.toml"
        route = data["route"]
        assert route["name"] == "health_proxy_demo"
        assert "capabilities" in route
        assert len(route["capabilities"]) > 0

    def test_routes_dsl_yaml_loadable(self) -> None:
        """health.dsl.yaml для health_proxy_demo должен загружаться без ошибок."""
        yaml_path = _routes_root() / "health_proxy_demo" / "health.dsl.yaml"
        assert yaml_path.exists(), f"Файл не найден: {yaml_path}"
        with yaml_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert data is not None
        assert "from" in data, "Ключ 'from' обязателен в DSL-файле"
        assert "steps" in data, "Ключ 'steps' обязателен в DSL-файле"
        assert "to" in data, "Ключ 'to' обязателен в DSL-файле"
        assert len(data["steps"]) > 0


class TestEchoDemoRoute:
    """Smoke-тесты для reference route echo_demo."""

    def test_routes_toml_loadable(self) -> None:
        """route.toml для echo_demo должен загружаться без ошибок."""
        toml_path = _routes_root() / "echo_demo" / "route.toml"
        assert toml_path.exists(), f"Файл не найден: {toml_path}"
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
        assert "route" in data, "Секция [route] обязательна в route.toml"
        route = data["route"]
        assert route["name"] == "echo_demo"
        assert "capabilities" in route
        assert len(route["capabilities"]) > 0

    def test_routes_dsl_yaml_loadable(self) -> None:
        """echo.dsl.yaml для echo_demo должен загружаться без ошибок."""
        yaml_path = _routes_root() / "echo_demo" / "echo.dsl.yaml"
        assert yaml_path.exists(), f"Файл не найден: {yaml_path}"
        with yaml_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert data is not None
        assert "from" in data, "Ключ 'from' обязателен в DSL-файле"
        assert "steps" in data, "Ключ 'steps' обязателен в DSL-файле"
        assert "to" in data, "Ключ 'to' обязателен в DSL-файле"
        assert len(data["steps"]) > 0
