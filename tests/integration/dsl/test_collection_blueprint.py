"""Integration-тест collection blueprint через ExecutionEngine.

Покрывает декларативное описание маршрута в YAML с процессорами
``.collect``, ``.find_all``, ``.group_by`` и запуск через
:class:`ExecutionEngine`.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


@pytest.mark.integration
async def test_collection_blueprint_collect() -> None:
    yaml_text = """
route_id: test.collection.collect
source: internal:test
steps:
  - collect:
      field: name
"""
    pipeline = load_pipeline_from_yaml(yaml_text)
    engine = ExecutionEngine()
    exchange = await engine.execute(
        pipeline, body=[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
    )
    assert exchange.out_message.body == ["Alice", "Bob"]


@pytest.mark.integration
async def test_collection_blueprint_find_all() -> None:
    yaml_text = """
route_id: test.collection.find_all
source: internal:test
steps:
  - find_all:
      condition: age > 18
"""
    pipeline = load_pipeline_from_yaml(yaml_text)
    engine = ExecutionEngine()
    exchange = await engine.execute(
        pipeline,
        body=[
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 16},
            {"name": "Charlie", "age": 25},
        ],
    )
    assert exchange.out_message.body == [
        {"name": "Alice", "age": 30},
        {"name": "Charlie", "age": 25},
    ]


@pytest.mark.integration
async def test_collection_blueprint_group_by() -> None:
    yaml_text = """
route_id: test.collection.group_by
source: internal:test
steps:
  - group_by:
      field: category
"""
    pipeline = load_pipeline_from_yaml(yaml_text)
    engine = ExecutionEngine()
    exchange = await engine.execute(
        pipeline,
        body=[
            {"name": "Alice", "category": "A"},
            {"name": "Bob", "category": "B"},
            {"name": "Charlie", "category": "A"},
        ],
    )
    assert exchange.out_message.body == {
        "A": [{"name": "Alice", "category": "A"}, {"name": "Charlie", "category": "A"}],
        "B": [{"name": "Bob", "category": "B"}],
    }
