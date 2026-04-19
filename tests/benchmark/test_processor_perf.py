"""Performance benchmarks — регистрируют baseline latency per processor.

Run:
    pytest tests/benchmark/ --benchmark-only

Для regression detection:
    pytest tests/benchmark/ --benchmark-compare=baseline --benchmark-compare-fail=mean:10%
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def simple_exchange():
    from app.dsl.engine.exchange import Exchange, Message
    return Exchange(
        in_message=Message(
            body={"id": 1, "name": "test", "amount": 100.5},
            headers={"X-Test": "1"},
        )
    )


@pytest.fixture
def simple_context():
    from app.dsl.engine.context import ExecutionContext
    return ExecutionContext()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.benchmark(group="core")
def test_set_header_benchmark(benchmark, simple_exchange, simple_context):
    from app.dsl.engine.processors.core import SetHeaderProcessor

    proc = SetHeaderProcessor(key="x-test", value="1")
    benchmark(_run, proc.process(simple_exchange, simple_context))


@pytest.mark.benchmark(group="core")
def test_transform_benchmark(benchmark, simple_exchange, simple_context):
    from app.dsl.engine.processors.core import TransformProcessor

    proc = TransformProcessor(expression="{id: id, name: name}")
    benchmark(_run, proc.process(simple_exchange, simple_context))


@pytest.mark.benchmark(group="json")
def test_fast_json_encode_benchmark(benchmark):
    from app.utilities.fast_json import encode

    data = {"id": 1, "items": list(range(100)), "name": "test" * 10}
    benchmark(encode, data)


@pytest.mark.benchmark(group="json")
def test_orjson_baseline(benchmark):
    import orjson

    data = {"id": 1, "items": list(range(100)), "name": "test" * 10}
    benchmark(orjson.dumps, data, default=str)


@pytest.mark.benchmark(group="slo")
def test_slo_tracker_record_benchmark(benchmark):
    from app.infrastructure.application.slo_tracker import SLOTracker

    tracker = SLOTracker()
    benchmark(tracker.record, "test.route", 50.0, False)


@pytest.mark.benchmark(group="slo")
def test_slo_percentile_benchmark(benchmark):
    from app.infrastructure.application.slo_tracker import SLOTracker

    tracker = SLOTracker()
    for i in range(1000):
        tracker.record("test.route", float(i % 100), False)
    benchmark(tracker.get_route_stats, "test.route")
