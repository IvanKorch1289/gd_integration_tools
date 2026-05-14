"""Smoke-тесты для :file:`src/backend/dsl/blueprints/api_normalize.yaml`.

Проверяют:
    * blueprint YAML корректно парсится через ``yaml.safe_load``;
    * присутствуют обязательные секции (``blueprint``, ``params``,
      ``from``, ``steps``, ``to``);
    * объявлен ровно один источник ``http`` с методом и path;
    * последовательность ``steps`` включает CRUD pass-through ключевые шаги.
"""
# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


@pytest.fixture(scope="module")
def blueprint() -> dict[str, Any]:
    """Загружает и парсит ``api_normalize.yaml`` один раз на модуль."""
    path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "backend"
        / "dsl"
        / "blueprints"
        / "api_normalize.yaml"
    )
    assert path.exists(), f"Blueprint не найден: {path}"
    raw = path.read_text(encoding="utf-8")
    return yaml.safe_load(raw)


def test_blueprint_loads(blueprint: dict[str, Any]) -> None:
    """YAML парсится в словарь верхнего уровня."""
    assert isinstance(blueprint, dict)
    assert blueprint.get("blueprint") == "api_normalize"
    assert blueprint.get("version")


def test_blueprint_has_required_sections(blueprint: dict[str, Any]) -> None:
    """Blueprint содержит все обязательные top-level секции."""
    required = {"blueprint", "version", "params", "from", "steps", "to"}
    missing = required - set(blueprint.keys())
    assert not missing, f"Отсутствуют секции: {missing}"


def test_blueprint_has_http_source(blueprint: dict[str, Any]) -> None:
    """Секция ``from`` объявляет HTTP-источник с method и path."""
    src = blueprint["from"]
    assert isinstance(src, dict)
    assert "http" in src
    http = src["http"]
    assert http.get("method")
    assert http.get("path")


def test_blueprint_steps_include_crud_pass_through(blueprint: dict[str, Any]) -> None:
    """Steps содержат CRUD-pass-through критические операции.

    Reference-pattern обязан содержать минимум:
        * get_setting — чтение URL/secret из конфигурации;
        * validate_request — входная валидация;
        * crud_create — собственно pass-through сохранение;
        * publish_event — оповещение Sink;
        * audit — фиксация в audit-журнале.
    """
    steps = blueprint["steps"]
    assert isinstance(steps, list)
    step_keys: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or len(step) != 1:
            continue
        step_keys.append(next(iter(step)))
    expected_subset = {
        "get_setting",
        "validate_request",
        "crud_create",
        "publish_event",
        "audit",
    }
    missing = expected_subset - set(step_keys)
    assert not missing, (
        f"В steps blueprint'а отсутствуют ключевые шаги: {missing}. "
        f"Найдено: {step_keys}"
    )


def test_blueprint_params_declare_route_id(blueprint: dict[str, Any]) -> None:
    """Список ``params`` объявляет ``route_id`` как required."""
    params = blueprint["params"]
    assert isinstance(params, list)
    route_id_param = next((p for p in params if p.get("name") == "route_id"), None)
    assert route_id_param is not None, "Параметр route_id обязателен"
    assert route_id_param.get("required") is True
