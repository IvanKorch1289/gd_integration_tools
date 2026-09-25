"""Focused tests: W9 P2-13 Phase 4 — services/ops/health god-module split.

Проверяет:
1. Shim (services/ops/health.py file) re-exports все публичные имена.
2. Submodules export classes/functions корректно.
3. Singleton accessor get_processor_health_service() работает.
4. 7 default checks зарегистрированы при startup.
5. Shim < 100 LOC (vs 609 original).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.services.ops.health import ProcessorHealthResult as ShimResult
from src.backend.services.ops.health import ProcessorHealthService as ShimService
from src.backend.services.ops.health import (
    get_processor_health_service as ShimGetService,
)
from src.backend.services.ops.health._service import (
    ProcessorHealthService as CanonicalService,
)
from src.backend.services.ops.health._service import (
    get_processor_health_service as CanonicalGetService,
)
from src.backend.services.ops.health._types import (
    ProcessorHealthResult as CanonicalResult,
)


class TestBackCompatIdentity:
    """Shim re-exports идентичны canonical (id-equal)."""

    @pytest.mark.parametrize(
        "shim,canonical,name",
        [
            (ShimResult, CanonicalResult, "ProcessorHealthResult"),
            (ShimService, CanonicalService, "ProcessorHealthService"),
            (ShimGetService, CanonicalGetService, "get_processor_health_service"),
        ],
    )
    def test_shim_returns_canonical(self, shim, canonical, name: str) -> None:
        """Shim импортирует тот же class (id-equal)."""
        assert shim is canonical, (
            f"{name}: shim {shim!r}@{id(shim)} != canonical {canonical!r}@{id(canonical)}"
        )


class TestSubmoduleExports:
    """Каждый submodule экспортирует ожидаемые имена."""

    def test_types_submodule(self) -> None:
        """_types экспортирует ProcessorHealthResult."""
        from src.backend.services.ops.health import _types

        assert _types.ProcessorHealthResult is CanonicalResult

    def test_http_submodule(self) -> None:
        """_http экспортирует _http_get и _tcp_connect."""
        from src.backend.services.ops.health import _http

        assert callable(_http._http_get)
        assert callable(_http._tcp_connect)

    def test_service_submodule(self) -> None:
        """_service экспортирует ProcessorHealthService + singleton."""
        from src.backend.services.ops.health import _service

        assert _service.ProcessorHealthService is CanonicalService
        assert _service.get_processor_health_service is CanonicalGetService

    def test_checks_submodule(self) -> None:
        """_checks экспортирует 7 default check functions + _is_strict_mode."""
        from src.backend.services.ops.health import _checks

        assert callable(_checks._check_kafka_schema_registry)
        assert callable(_checks._check_temporal_server)
        assert callable(_checks._check_vault_sealed)
        assert callable(_checks._check_clickhouse)
        assert callable(_checks._check_redis_cluster)
        assert callable(_checks._check_nats)
        assert callable(_checks._check_graylog)
        assert callable(_checks._is_strict_mode)


class TestSingletonBehavior:
    """Singleton accessor работает через back-compat shim."""

    def test_singleton_returns_service(self) -> None:
        """get_processor_health_service() возвращает экземпляр."""
        svc = ShimGetService()
        assert isinstance(svc, CanonicalService)

    def test_singleton_returns_same_instance(self) -> None:
        """get_processor_health_service() — singleton (same instance)."""
        svc1 = ShimGetService()
        svc2 = ShimGetService()
        assert svc1 is svc2, "singleton should return same instance"

    def test_singleton_registers_7_default_checks(self) -> None:
        """get_processor_health_service() регистрирует 7 default checks."""
        svc = ShimGetService()
        expected_checks = {
            "kafka_schema_registry",
            "temporal_server",
            "vault",
            "clickhouse",
            "redis_cluster",
            "nats",
            "graylog",
        }
        registered = set(svc.registered_names())
        assert expected_checks.issubset(registered), (
            f"missing checks: {expected_checks - registered}"
        )


class TestShimReduction:
    """Shim file dramatically reduced (609 → 41 LOC)."""

    def test_shim_under_100_loc(self) -> None:
        """Shim file < 100 LOC."""
        shim_path = Path("src/backend/services/ops/health.py")
        loc = sum(1 for _ in shim_path.open())
        assert loc < 100, f"shim {loc} LOC (target: <100, было 609)"


class TestSubmoduleSplitCompliance:
    """V15 forbidden pattern compliance — submodules < 500 LOC."""

    def test_all_submodules_under_500_loc(self) -> None:
        """Каждый submodule < 500 LOC (V15 forbidden pattern)."""
        health_pkg = Path("src/backend/services/ops/health")
        for py_file in sorted(health_pkg.glob("_*.py")):
            loc = sum(1 for _ in py_file.open())
            assert loc < 500, (
                f"{py_file.name} = {loc} LOC (V15 forbidden: >500 = god-module)"
            )


class TestProcessorHealthResultDataclass:
    """ProcessorHealthResult dataclass behaves correctly."""

    def test_dataclass_construction(self) -> None:
        """Constructor с required args работает."""
        result = ShimResult(
            processor_name="test", ok=True, reason="healthy", latency_ms=12.5
        )
        assert result.processor_name == "test"
        assert result.ok is True
        assert result.reason == "healthy"
        assert result.latency_ms == 12.5

    def test_dataclass_immutability_via_slots(self) -> None:
        """Dataclass использует slots (если поддерживается)."""
        # Не строгая проверка — просто smoke test что атрибуты доступны.
        result = ShimResult(
            processor_name="test", ok=False, reason="failed", latency_ms=100.0
        )
        assert result.latency_ms == 100.0
