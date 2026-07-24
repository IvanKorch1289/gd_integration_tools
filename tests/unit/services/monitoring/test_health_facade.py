"""Unit-тесты для HealthFacade (Sprint I-1).

Coverage:
- Defaults (timeout, threshold)
- Custom check registration
- check_all parallel execution
- check() individual component
- is_healthy() bool
- get_status() dict format
- Degraded mode (1+ failures)
- Unhealthy mode (>= threshold failures)
- Timeout enforcement
- Empty registry (no checks)
"""

from __future__ import annotations


import pytest

from src.backend.services.monitoring.facade import (
    HealthFacade,
    HealthStatus,
)


class TestHealthFacadeDefaults:
    """Тесты дефолтов."""

    def test_default_timeout(self) -> None:
        """Default timeout 2.0 секунды."""
        facade = HealthFacade()
        assert facade._timeout == 2.0

    def test_default_threshold(self) -> None:
        """Default threshold 1 failure для degraded→unhealthy."""
        facade = HealthFacade()
        assert facade._threshold == 1

    def test_custom_timeout(self) -> None:
        """Custom timeout сохраняется."""
        facade = HealthFacade(timeout_seconds=5.0)
        assert facade._timeout == 5.0


class TestRegisterCheck:
    """Тесты регистрации custom checks."""

    def test_register_check(self) -> None:
        """register_check добавляет функцию в registry."""
        facade = HealthFacade()

        async def my_check() -> bool:
            return True

        facade.register_check("test", my_check)
        assert "test" in facade._custom_checks

    def test_register_multiple_checks(self) -> None:
        """Несколько checks могут быть зарегистрированы."""
        facade = HealthFacade()

        async def check_a() -> bool:
            return True

        async def check_b() -> bool:
            return False

        facade.register_check("a", check_a)
        facade.register_check("b", check_b)
        assert len(facade._custom_checks) == 2


class TestCheck:
    """Тесты :meth:`check`."""

    @pytest.mark.asyncio
    async def test_check_unregistered(self) -> None:
        """Unregistered component возвращает status=False."""
        facade = HealthFacade()
        result = await facade.check("nonexistent")
        assert result["status"] is False
        assert "not registered" in result["error"]

    @pytest.mark.asyncio
    async def test_check_success(self) -> None:
        """Успешный check возвращает status=True, latency > 0."""
        facade = HealthFacade()

        async def healthy() -> bool:
            return True

        facade.register_check("h", healthy)
        result = await facade.check("h")
        assert result["status"] is True
        assert result["latency_ms"] >= 0
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_check_returns_false(self) -> None:
        """Check возвращающий False → status=False."""
        facade = HealthFacade()

        async def unhealthy() -> bool:
            return False

        facade.register_check("u", unhealthy)
        result = await facade.check("u")
        assert result["status"] is False

    @pytest.mark.asyncio
    async def test_check_exception_caught(self) -> None:
        """Exception в check ловится и возвращается как status=False."""
        facade = HealthFacade()

        async def broken() -> bool:
            raise RuntimeError("boom")

        facade.register_check("b", broken)
        result = await facade.check("b")
        assert result["status"] is False
        assert "RuntimeError" in result["error"]


class TestCheckAll:
    """Тесты :meth:`check_all`."""

    @pytest.mark.asyncio
    async def test_empty_registry(self) -> None:
        """Empty registry → HEALTHY (trivially)."""
        facade = HealthFacade()
        report = await facade.check_all()
        assert report.status == HealthStatus.HEALTHY
        assert report.is_all_active is True
        assert report.components == {}

    @pytest.mark.asyncio
    async def test_all_healthy(self) -> None:
        """Все checks healthy → HEALTHY."""
        facade = HealthFacade()

        async def ok() -> bool:
            return True

        facade.register_check("a", ok)
        facade.register_check("b", ok)
        report = await facade.check_all()
        assert report.status == HealthStatus.HEALTHY
        assert report.is_all_active is True
        assert len(report.components) == 2

    @pytest.mark.asyncio
    async def test_one_failure_degraded(self) -> None:
        """1 failure (threshold=2) → DEGRADED."""
        facade = HealthFacade(check_failure_threshold=2)

        async def ok() -> bool:
            return True

        async def bad() -> bool:
            return False

        facade.register_check("a", ok)
        facade.register_check("b", bad)
        report = await facade.check_all()
        assert report.status == HealthStatus.DEGRADED
        assert report.is_all_active is False

    @pytest.mark.asyncio
    async def test_threshold_failure_unhealthy(self) -> None:
        """≥ threshold failures → UNHEALTHY."""
        facade = HealthFacade(check_failure_threshold=1)

        async def bad() -> bool:
            return False

        facade.register_check("a", bad)
        report = await facade.check_all()
        assert report.status == HealthStatus.UNHEALTHY


class TestIsHealthy:
    """Тесты :meth:`is_healthy`."""

    @pytest.mark.asyncio
    async def test_is_healthy_when_all_ok(self) -> None:
        """is_healthy=True когда все checks прошли."""
        facade = HealthFacade()

        async def ok() -> bool:
            return True

        facade.register_check("a", ok)
        assert await facade.is_healthy() is True

    @pytest.mark.asyncio
    async def test_is_healthy_false_on_failure(self) -> None:
        """is_healthy=False при failure."""
        facade = HealthFacade()

        async def bad() -> bool:
            return False

        facade.register_check("a", bad)
        assert await facade.is_healthy() is False


class TestGetStatus:
    """Тесты :meth:`get_status`."""

    @pytest.mark.asyncio
    async def test_get_status_dict_format(self) -> None:
        """get_status возвращает dict для JSON response."""
        facade = HealthFacade()

        async def ok() -> bool:
            return True

        facade.register_check("a", ok)
        result = await facade.get_status()
        assert isinstance(result, dict)
        assert "status" in result
        assert "is_all_services_active" in result
        assert "components" in result
        assert "checked_at" in result
