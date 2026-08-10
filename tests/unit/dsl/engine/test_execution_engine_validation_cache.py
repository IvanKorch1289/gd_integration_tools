"""Regression-тесты для cache валидации в ``ExecutionEngine._cached_validate``.

Контракт:
* cache-hit только когда ``(route_id, processors)`` совпадает с прошлым вызовом;
* добавление/удаление процессора в pipeline обязано инвалидировать запись;
* явный ``invalidate_validation_cache`` сбрасывает записи (per-route и целиком).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.processors.base import BaseProcessor


class _NoopProcessor(BaseProcessor):
    """Минимальный процессор с фиксированным именем."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name)

    async def process(self, exchange: Any, context: Any) -> None:
        return None


def _make_pipeline(route_id: str, names: list[str]) -> Any:
    """Pipeline с указанными именами процессоров (без реальной логики)."""
    from src.backend.dsl.engine.pipeline import Pipeline

    pipeline = Pipeline(route_id=route_id)
    for n in names:
        pipeline.add_processor(_NoopProcessor(n))
    return pipeline


@pytest.mark.unit
class TestValidationCacheInvalidation:
    """``_cached_validate`` не должен возвращать stale-результат."""

    def test_same_pipeline_returns_cached_result(self) -> None:
        """Идентичный pipeline → cache hit (тот же объект ValidationResult)."""
        engine = ExecutionEngine(validate_before_execute=True)
        pipeline = _make_pipeline("r1", ["a", "b"])

        r1 = engine._cached_validate(pipeline)
        r2 = engine._cached_validate(pipeline)

        assert r1 is r2  # cache hit → тот же объект

    def test_added_processor_invalidates_cache(self) -> None:
        """Добавление процессора в pipeline → cache miss, новый ValidationResult."""
        engine = ExecutionEngine(validate_before_execute=True)
        pipeline = _make_pipeline("r2", ["a"])

        cached_before = engine._cached_validate(pipeline)
        pipeline.add_processor(_NoopProcessor("b"))
        cached_after = engine._cached_validate(pipeline)

        assert cached_before is not cached_after

    def test_invalidate_validation_cache_by_route(self) -> None:
        """``invalidate_validation_cache(route_id)`` сбрасывает записи одного route."""
        engine = ExecutionEngine(validate_before_execute=True)
        pipeline = _make_pipeline("r3", ["a"])

        engine._cached_validate(pipeline)
        assert len(engine._validation_cache) == 1

        engine.invalidate_validation_cache(route_id="r3")
        assert len(engine._validation_cache) == 0

    def test_invalidate_validation_cache_all(self) -> None:
        """``invalidate_validation_cache()`` без аргумента сбрасывает весь cache."""
        engine = ExecutionEngine(validate_before_execute=True)
        engine._cached_validate(_make_pipeline("r_a", ["a"]))
        engine._cached_validate(_make_pipeline("r_b", ["b"]))
        assert len(engine._validation_cache) == 2

        engine.invalidate_validation_cache()
        assert len(engine._validation_cache) == 0

    def test_invalidate_validation_cache_does_not_touch_other_routes(self) -> None:
        """Сброс по route_id не задевает записи других маршрутов."""
        engine = ExecutionEngine(validate_before_execute=True)
        engine._cached_validate(_make_pipeline("r_keep", ["a"]))
        engine._cached_validate(_make_pipeline("r_drop", ["a"]))
        assert len(engine._validation_cache) == 2

        engine.invalidate_validation_cache(route_id="r_drop")
        assert len(engine._validation_cache) == 1
        assert all(k[0] == "r_keep" for k in engine._validation_cache)

    def test_different_route_ids_dont_collide(self) -> None:
        """Разные route_id → разные cache-записи даже при одинаковых процессорах."""
        engine = ExecutionEngine(validate_before_execute=True)
        engine._cached_validate(_make_pipeline("r1", ["a"]))
        engine._cached_validate(_make_pipeline("r2", ["a"]))
        assert len(engine._validation_cache) == 2
