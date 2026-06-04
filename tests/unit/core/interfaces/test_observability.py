"""Unit tests for src.backend.core.interfaces.observability."""

from __future__ import annotations

from src.backend.core.interfaces.observability import (
    CircuitBreakerMetricsRecorder,
    CorrelationIdProvider,
    HealthAggregatorProtocol,
    HealthCheckProtocol,
    HealthCheckSessionProtocol,
    SLOTrackerProtocol,
    TemporalMetricsExporter,
)


class TestSLOTrackerProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            def record(
                self, route_id: str, latency_ms: float, is_error: bool = False
            ) -> None:
                pass

            def get_report(self) -> dict[str, object]:
                return {}

            def get_route_stats(self, route_id: str) -> dict[str, object]:
                return {}

            def reset(self) -> None:
                pass

        assert isinstance(Fake(), SLOTrackerProtocol)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), SLOTrackerProtocol)


class TestHealthAggregatorProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def check_all(self, *, mode: str = "fast") -> dict[str, object]:
                return {}

            async def check_single(
                self, name: str, *, mode: str = "fast"
            ) -> dict[str, object]:
                return {}

        assert isinstance(Fake(), HealthAggregatorProtocol)


class TestHealthCheckSessionProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def check_database(self) -> bool:
                return True

            async def check_redis(self) -> bool:
                return True

            async def check_s3(self) -> bool:
                return True

            async def check_s3_bucket(self) -> bool:
                return True

            async def check_graylog(self) -> bool:
                return True

            async def check_smtp(self) -> bool:
                return True

            async def check_rabbitmq(self) -> bool:
                return True

            async def check_all_services(self) -> dict[str, object]:
                return {}

        assert isinstance(Fake(), HealthCheckSessionProtocol)


class TestHealthCheckProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            def __call__(self) -> object:
                return object()

        assert isinstance(Fake(), HealthCheckProtocol)


class TestCircuitBreakerMetricsRecorder:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            def __call__(self, *, client: str, host: str, state: str) -> None:
                pass

        assert isinstance(Fake(), CircuitBreakerMetricsRecorder)


class TestCorrelationIdProvider:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            def __call__(self) -> str | None:
                return "cid"

        assert isinstance(Fake(), CorrelationIdProvider)


class TestTemporalMetricsExporter:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            def set_task_queue_depth(self, task_queue: str, depth: int) -> None:
                pass

            def record_scale_event(self, action: str) -> None:
                pass

            def set_workers_active(self, task_queue: str, count: int) -> None:
                pass

        assert isinstance(Fake(), TemporalMetricsExporter)
