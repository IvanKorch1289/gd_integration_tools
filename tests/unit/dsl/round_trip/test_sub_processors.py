"""W26.1 — Round-trip тесты sub-processors (Retry / TryCatch / Parallel / Saga / Choice).

Проверяет, что для control-flow процессоров с вложенными sub-pipeline'ами цикл
``RouteBuilder → Pipeline.to_dict → load_pipeline_from_yaml → to_dict`` сохраняет
эквивалентность представления.

Покрывает:
- Retry с примитивными children;
- TryCatch с try / catch / finally ветками;
- Parallel с двумя branches и strategy="all";
- Saga с двумя шагами + compensate;
- Choice через JMESPath (``expr``) + ``otherwise``;
- Глубокая рекурсия (Retry внутри TryCatch);
- Choice с legacy callable predicate → ``to_spec() is None``.
"""

# ruff: noqa: S101

from __future__ import annotations

import yaml

from src.dsl.builder import RouteBuilder
from src.dsl.engine.processors import (
    ChoiceBranch,
    LogProcessor,
    RetryProcessor,
    SagaStep,
    SetHeaderProcessor,
    TransformProcessor,
    TryCatchProcessor,
)
from src.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


def test_retry_round_trip() -> None:
    """Retry с двумя примитивными children сохраняет состав после round-trip."""
    builder = RouteBuilder.from_("rt.retry", source="test:rt.retry").retry(
        processors=[
            LogProcessor(level="info"),
            SetHeaderProcessor(key="x-retry", value="1"),
        ],
        max_attempts=4,
        delay_seconds=0.5,
        backoff="fixed",
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    retry_spec = original["processors"][0]["retry"]
    assert retry_spec["max_attempts"] == 4
    assert retry_spec["backoff"] == "fixed"
    assert len(retry_spec["processors"]) == 2


def test_try_catch_round_trip() -> None:
    """TryCatch со всеми тремя ветками сериализуется и читается обратно."""
    builder = RouteBuilder.from_("rt.try", source="test:rt.try").do_try(
        try_processors=[TransformProcessor(expression="body")],
        catch_processors=[LogProcessor(level="error")],
        finally_processors=[SetHeaderProcessor(key="x-finalized", value="yes")],
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    do_try = original["processors"][0]["do_try"]
    assert "try_processors" in do_try
    assert "catch_processors" in do_try
    assert "finally_processors" in do_try


def test_parallel_round_trip() -> None:
    """Parallel с двумя branches и strategy='all' переживает round-trip."""
    builder = RouteBuilder.from_("rt.par", source="test:rt.par").parallel(
        branches={
            "left": [LogProcessor(level="info")],
            "right": [SetHeaderProcessor(key="x-r", value="r")],
        },
        strategy="all",
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    parallel = original["processors"][0]["parallel"]
    assert parallel["strategy"] == "all"
    assert set(parallel["branches"].keys()) == {"left", "right"}


def test_saga_round_trip() -> None:
    """Saga из двух шагов, оба с compensate, сериализуется без потерь."""
    builder = RouteBuilder.from_("rt.saga", source="test:rt.saga").saga(
        steps=[
            SagaStep(
                forward=LogProcessor(level="info"),
                compensate=SetHeaderProcessor(key="x-undo-1", value="1"),
            ),
            SagaStep(
                forward=TransformProcessor(expression="body"),
                compensate=SetHeaderProcessor(key="x-undo-2", value="2"),
            ),
        ]
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    saga = original["processors"][0]["saga"]
    assert len(saga["steps"]) == 2
    assert "compensate" in saga["steps"][0]
    assert "compensate" in saga["steps"][1]


def test_choice_jmespath_round_trip() -> None:
    """Choice через JMESPath ``expr`` + ``otherwise`` round-trip-сериализуется."""
    builder = RouteBuilder.from_("rt.choice", source="test:rt.choice").choice(
        when=[
            ChoiceBranch(
                expr="status == 'ok'",
                processors=[LogProcessor(level="info")],
            ),
            ChoiceBranch(
                expr="status == 'fail'",
                processors=[SetHeaderProcessor(key="x-fail", value="1")],
            ),
        ],
        otherwise=[LogProcessor(level="warning")],
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    choice = original["processors"][0]["choice"]
    assert len(choice["when"]) == 2
    assert choice["when"][0]["expr"] == "status == 'ok'"
    assert "otherwise" in choice


def test_nested_retry_inside_try_catch_round_trip() -> None:
    """Глубокая рекурсия: Retry внутри TryCatch.try сохраняется."""
    builder = RouteBuilder.from_("rt.nested", source="test:rt.nested").do_try(
        try_processors=[
            RetryProcessor(
                processors=[LogProcessor(level="info")],
                max_attempts=2,
                delay_seconds=0.1,
                backoff="fixed",
            )
        ],
        catch_processors=[LogProcessor(level="error")],
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    do_try = original["processors"][0]["do_try"]
    inner_retry = do_try["try_processors"][0]["retry"]
    assert inner_retry["max_attempts"] == 2
    assert inner_retry["backoff"] == "fixed"


def test_choice_with_callable_skipped() -> None:
    """Choice с legacy callable predicate → to_spec() is None → дроп при write-back."""
    builder = (
        RouteBuilder.from_("rt.legacy", source="test:rt.legacy")
        .set_header(key="x-before", value="v")
        .choice(
            when=[(lambda ex: True, [LogProcessor(level="info")])],
            otherwise=[LogProcessor(level="warning")],
        )
        .log(level="info")
    )
    pipeline = builder.build()
    spec = pipeline.to_dict()
    methods = [next(iter(p)) for p in spec["processors"]]
    assert methods == ["set_header", "log"]
    assert "choice" not in methods


def test_try_catch_with_callable_child_skipped() -> None:
    """TryCatch с несериализуемым child (dispatch_action+payload_factory) → None."""
    from src.dsl.engine.processors import DispatchActionProcessor

    inner = TryCatchProcessor(
        try_processors=[
            DispatchActionProcessor(
                action="x.y", payload_factory=lambda ex: {"v": 1}
            )
        ],
        catch_processors=[LogProcessor(level="error")],
    )
    assert inner.to_spec() is None
