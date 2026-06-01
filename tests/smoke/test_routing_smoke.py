"""S36 w1 — Smoke test: DSL RouteBuilder + PipelineCompiler.

Проверяет критический путь: собрать pipeline из RouteBuilder
и скомпилировать через PipelineCompiler с LRU-кэшем.

Не поднимает FastAPI, Temporal, Redis — тестирует ядро DSL
end-to-end на уровне Python.
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import PipelineCompiler


def test_route_builder_creates_pipeline() -> None:
    """RouteBuilder.from_ → pipeline с одним шагом log()."""
    builder = RouteBuilder.from_("smoke.routing.basic", source="test")
    pipeline = builder.log(level="info").build()

    assert pipeline.route_id == "smoke.routing.basic"
    assert len(pipeline.processors) == 1


def test_pipeline_compiler_caches_repeated_compilations() -> None:
    """PipelineCompiler.compile() возвращает идентичный результат
    для повторных вызовов (LRU-кеш работает)."""
    compiler = PipelineCompiler()
    builder = RouteBuilder.from_("smoke.routing.cache", source="test")
    pipeline = builder.log(level="info").build()

    first = compiler.compile(pipeline)
    second = compiler.compile(pipeline)

    assert first.is_valid is True
    assert second.is_valid is True
    assert first.processor_names == second.processor_names


def test_pipeline_compiler_cache_clear() -> None:
    """PipelineCompiler.clear_cache() сбрасывает LRU-кеш."""
    compiler = PipelineCompiler()
    builder = RouteBuilder.from_("smoke.routing.clear", source="test")
    pipeline = builder.log(level="info").build()

    compiler.compile(pipeline)
    compiler.clear_cache()
    cache_info_after = compiler._compile_cached.cache_info()  # noqa: SLF001

    assert cache_info_after.currsize == 0


def test_empty_pipeline_reports_invalid() -> None:
    """Pipeline без процессоров → is_valid=False."""
    from src.backend.dsl.engine.pipeline import Pipeline

    compiler = PipelineCompiler()
    empty = Pipeline(route_id="smoke.routing.empty", processors=[])
    result = compiler.compile(empty)

    assert result.is_valid is False
    assert result.processor_names == ()
