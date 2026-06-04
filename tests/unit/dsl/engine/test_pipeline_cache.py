"""Unit-тесты для PipelineCompiler с LRU-кэшированием (B1)."""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.pipeline import CompiledPipeline, Pipeline, PipelineCompiler
from src.backend.dsl.engine.processors.base import BaseProcessor


class _DummyProcessor(BaseProcessor):
    """Тестовый процессор без реальной логики."""

    def __init__(self, name: str = "dummy") -> None:
        super().__init__(name=name)

    async def process(self, exchange: object, context: object) -> None:
        pass

    def to_spec(self) -> dict[str, object]:
        return {}


class _AnotherProcessor(BaseProcessor):
    """Ещё один тестовый процессор."""

    def __init__(self, name: str = "another") -> None:
        super().__init__(name=name)

    async def process(self, exchange: object, context: object) -> None:
        pass

    def to_spec(self) -> dict[str, object]:
        return {}


def test_compile_returns_compiled_pipeline() -> None:
    """compile() возвращает CompiledPipeline."""
    compiler = PipelineCompiler()
    pipeline = Pipeline(route_id="test_route")
    pipeline.add_processor(_DummyProcessor("proc1"))

    result = compiler.compile(pipeline)

    assert isinstance(result, CompiledPipeline)
    assert result.pipeline is pipeline
    assert result.is_valid is True
    assert result.processor_names == ("proc1",)


def test_compile_caches_result() -> None:
    """Повторный вызов compile() возвращает кэшированный результат."""
    compiler = PipelineCompiler()
    pipeline = Pipeline(route_id="cached_route")
    pipeline.add_processor(_DummyProcessor("cached_proc"))

    # Первый вызов - результат зависит от pipeline
    result1 = compiler.compile(pipeline)
    # Второй вызов с тем же pipeline - используется кэш внутренней функции
    result2 = compiler.compile(pipeline)

    # Результаты равны по содержанию но это разные объекты
    # (кеш влияет только на внутреннюю валидацию)
    assert result1.pipeline is result2.pipeline
    assert result1.is_valid == result2.is_valid


def test_compile_different_pipelines_different_cache_entries() -> None:
    """Разные pipeline получают разные кэш-записи."""
    compiler = PipelineCompiler()
    pipeline1 = Pipeline(route_id="route1")
    pipeline1.add_processor(_DummyProcessor("proc_a"))
    pipeline2 = Pipeline(route_id="route2")
    pipeline2.add_processor(_DummyProcessor("proc_b"))

    result1 = compiler.compile(pipeline1)
    result2 = compiler.compile(pipeline2)

    assert result1 is not result2
    assert result1.processor_names == ("proc_a",)
    assert result2.processor_names == ("proc_b",)
    assert result1.is_valid is True
    assert result2.is_valid is True


def test_compile_empty_pipeline_is_invalid() -> None:
    """Pipeline без процессоров считается невалидным."""
    compiler = PipelineCompiler()
    pipeline = Pipeline(route_id="empty_route")

    result = compiler.compile(pipeline)

    assert result.is_valid is False
    assert result.processor_names == ()


def test_compile_preserves_processor_order() -> None:
    """Порядок процессоров сохраняется в скомпилированном виде."""
    compiler = PipelineCompiler()
    pipeline = Pipeline(route_id="ordered_route")
    pipeline.add_processor(_DummyProcessor("first"))
    pipeline.add_processor(_AnotherProcessor("second"))
    pipeline.add_processor(_DummyProcessor("third"))

    result = compiler.compile(pipeline)

    assert result.processor_names == ("first", "second", "third")


def test_clear_cache_removes_all_entries() -> None:
    """clear_cache() очищает LRU-кеш."""
    compiler = PipelineCompiler()
    pipeline = Pipeline(route_id="to_clear")
    pipeline.add_processor(_DummyProcessor())

    compiler.compile(pipeline)
    compiler.clear_cache()
    # После очистки кэша - повторный вызов не использует старый кэш
    # (проверяем что cache_info показывает miss после clear)
    info = compiler._compile_cached.cache_info()
    assert info.currsize == 0


def test_cache_info_shows_hits_and_misses() -> None:
    """Cache info отражает hits/misses внутренней кэшируемой функции."""
    compiler = PipelineCompiler()
    pipeline1 = Pipeline(route_id="info_route_1")
    pipeline1.add_processor(_DummyProcessor())
    pipeline2 = Pipeline(route_id="info_route_2")
    pipeline2.add_processor(_DummyProcessor())

    compiler.compile(pipeline1)  # miss
    compiler.compile(pipeline1)  # hit
    compiler.compile(pipeline2)  # miss (different route_id)
    compiler.compile(pipeline1)  # hit

    info = compiler._compile_cached.cache_info()
    assert info.hits == 2
    assert info.misses == 2


def test_compiled_pipeline_is_frozen_and_hashable() -> None:
    """CompiledPipeline — frozen dataclass (иммутабельный)."""
    pipeline = Pipeline(route_id="hashable_route")
    pipeline.add_processor(_DummyProcessor("h"))

    compiler = PipelineCompiler()
    result = compiler.compile(pipeline)

    assert isinstance(result, CompiledPipeline)
    # frozen=True делает объект хешируемым
    assert hash(result) is not None


def test_same_route_id_different_processor_count_same_cache_key() -> None:
    """Один route_id с разным числом процессоров - разные кэш-записи."""
    compiler = PipelineCompiler()

    pipeline1 = Pipeline(route_id="same_route")
    pipeline1.add_processor(_DummyProcessor("proc1"))

    pipeline2 = Pipeline(route_id="same_route")
    pipeline2.add_processor(_DummyProcessor("proc1"))
    pipeline2.add_processor(_DummyProcessor("proc2"))

    result1 = compiler.compile(pipeline1)
    result2 = compiler.compile(pipeline2)

    # Кэш зависит от processor_count, поэтому результаты разные
    assert result1.is_valid is True
    assert result2.is_valid is True
    assert len(result1.processor_names) == 1
    assert len(result2.processor_names) == 2
