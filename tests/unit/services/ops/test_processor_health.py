"""Sprint 6 K2 — тесты ProcessorHealthService (services/ops/health.py)."""

# ruff: noqa: S101, SLF001

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_empty_service_returns_empty_results() -> None:
    """Сервис без зарегистрированных checks возвращает пустой список."""
    from src.backend.services.ops.health import ProcessorHealthService

    service = ProcessorHealthService()
    results = await service.check_all()
    assert results == []


@pytest.mark.asyncio
async def test_single_check_returns_result() -> None:
    """Один зарегистрированный check возвращает ProcessorHealthResult."""
    from src.backend.services.ops.health import (
        ProcessorHealthResult,
        ProcessorHealthService,
    )

    async def my_check() -> ProcessorHealthResult:
        return ProcessorHealthResult(
            processor_name="my_processor", ok=True, reason="test ok", latency_ms=1.0
        )

    service = ProcessorHealthService()
    service.register_check("my_processor", my_check)

    results = await service.check_all()
    assert len(results) == 1
    assert results[0].processor_name == "my_processor"
    assert results[0].ok is True


@pytest.mark.asyncio
async def test_failing_check_returns_ok_false() -> None:
    """Check с исключением возвращает ok=False с reason."""
    from src.backend.services.ops.health import ProcessorHealthService

    async def failing_check():
        raise ValueError("backend down")

    service = ProcessorHealthService()
    service.register_check("failing", failing_check)

    results = await service.check_all()
    assert len(results) == 1
    assert results[0].ok is False
    assert "ValueError" in results[0].reason or "backend down" in results[0].reason


@pytest.mark.asyncio
async def test_timeout_check_returns_ok_false() -> None:
    """Check, превышающий timeout, возвращает ok=False."""
    from src.backend.services.ops.health import ProcessorHealthService

    async def slow_check():
        await asyncio.sleep(10)  # Долго
        return None

    service = ProcessorHealthService(timeout_per_check_s=0.1)
    service.register_check("slow", slow_check)

    results = await service.check_all()
    assert len(results) == 1
    assert results[0].ok is False
    assert "timeout" in results[0].reason.lower()


@pytest.mark.asyncio
async def test_get_health_matrix_aggregates_results() -> None:
    """get_health_matrix агрегирует результаты в JSON-готовом формате."""
    from src.backend.services.ops.health import (
        ProcessorHealthResult,
        ProcessorHealthService,
    )

    async def ok_check():
        return ProcessorHealthResult("ok_proc", True, "ok", 5.0)

    async def bad_check():
        return ProcessorHealthResult("bad_proc", False, "down", 50.0)

    service = ProcessorHealthService()
    service.register_check("ok_proc", ok_check)
    service.register_check("bad_proc", bad_check)

    matrix = await service.get_health_matrix()
    assert matrix["overall"] == "degraded"  # хотя бы один failed
    assert matrix["registered_count"] == 2
    assert matrix["failed_count"] == 1
    assert "ok_proc" in matrix["checks"]
    assert "bad_proc" in matrix["checks"]
    assert matrix["checks"]["ok_proc"]["ok"] is True
    assert matrix["checks"]["bad_proc"]["ok"] is False


@pytest.mark.asyncio
async def test_all_ok_returns_overall_ok() -> None:
    """Если все checks ok=True — overall=ok."""
    from src.backend.services.ops.health import (
        ProcessorHealthResult,
        ProcessorHealthService,
    )

    async def check_a():
        return ProcessorHealthResult("a", True, "ok", 1.0)

    async def check_b():
        return ProcessorHealthResult("b", True, "ok", 1.0)

    service = ProcessorHealthService()
    service.register_check("a", check_a)
    service.register_check("b", check_b)

    matrix = await service.get_health_matrix()
    assert matrix["overall"] == "ok"
    assert matrix["failed_count"] == 0


def test_singleton_get_processor_health_service() -> None:
    """get_processor_health_service возвращает один singleton с 7 default-checks."""
    from src.backend.services.ops.health import get_processor_health_service

    s1 = get_processor_health_service()
    s2 = get_processor_health_service()
    assert s1 is s2
    # 7 default-checks: kafka_sr, temporal, vault, clickhouse, redis, nats, graylog
    assert len(s1.registered_names()) >= 7
    assert "kafka_schema_registry" in s1.registered_names()
    assert "temporal_server" in s1.registered_names()
    assert "vault" in s1.registered_names()
    assert "clickhouse" in s1.registered_names()
    assert "redis_cluster" in s1.registered_names()
    assert "nats" in s1.registered_names()
    assert "graylog" in s1.registered_names()


@pytest.mark.asyncio
async def test_default_checks_run_without_errors() -> None:
    """Default-checks из singleton'а проходят без exceptions (best-effort)."""
    from src.backend.services.ops.health import get_processor_health_service

    service = get_processor_health_service()
    matrix = await service.get_health_matrix()
    # Все 7 processor'ов есть в matrix
    assert matrix["registered_count"] >= 7
    # Не должно быть exceptions (best-effort stub'ы)
    for proc_name, info in matrix["checks"].items():
        assert "ok" in info
        assert "reason" in info
        assert "latency_ms" in info
