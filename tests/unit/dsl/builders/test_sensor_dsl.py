"""Unit tests для sensor DSL coverage (S55 W6).

Verifies that all S55 EIP + sensor + trigger DSL methods are exposed
on RouteBuilder через EIPMixin.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders.eip import EIPMixin

# All S55 DSL methods that должны быть exposed
EXPECTED_DSL_METHODS = [
    # EIP processors (S55 W1, W2)
    "routing_slip",
    "content_based_router",
    "sampling",
    # Triggers (S55 W4)
    "from_interval",
    "from_webhook",
    # Sensors (S55 W6)
    "from_file",
    "from_sql",
    "from_http",
    "from_s3",
]


class TestDSLCoverage:
    """Verify all major S55 EIPs are accessible via DSL."""

    @pytest.mark.parametrize("method_name", EXPECTED_DSL_METHODS)
    def test_dsl_method_present(self, method_name: str) -> None:
        """Каждый S55 pattern должен быть доступен через DSL."""
        assert hasattr(EIPMixin, method_name), (
            f"Missing DSL method: {method_name} (S55 incomplete)"
        )
        method = getattr(EIPMixin, method_name)
        assert callable(method), f"{method_name} must be callable"

    def test_routing_slip_documented(self) -> None:
        """DSL method должен иметь docstring с Camel reference."""
        method = getattr(EIPMixin, "routing_slip")
        assert method.__doc__ is not None
        assert "Camel" in method.__doc__
        assert "routingSlip" in method.__doc__

    def test_content_based_router_documented(self) -> None:
        method = getattr(EIPMixin, "content_based_router")
        assert method.__doc__ is not None
        assert "Camel" in method.__doc__
        assert "contentBasedRouter" in method.__doc__

    def test_sensor_dsl_documented(self) -> None:
        """from_file/sql/http/s3 должны ссылаться на Airflow docs."""
        for name in ["from_file", "from_sql", "from_http", "from_s3"]:
            method = getattr(EIPMixin, name)
            assert method.__doc__ is not None, f"{name} missing docstring"
            assert "Airflow" in method.__doc__, (
                f"{name} docstring should reference Airflow docs"
            )

    def test_dsl_methods_count(self) -> None:
        """Sanity check: minimum expected DSL method count."""
        dsl_methods = [
            m
            for m in dir(EIPMixin)
            if m.startswith(("from_", "routing_", "content_", "sampling"))
        ]
        assert len(dsl_methods) >= 9, f"Only {len(dsl_methods)} DSL methods found"


# ── Trigger registration smoke tests ─────────────────────────────


class TestTriggerRegistration:
    """Smoke tests: DSL methods register triggers correctly."""

    def test_from_interval_registers(self) -> None:
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        class _Stub:
            pass

        stub = _Stub()
        EIPMixin.from_interval(stub, 60.0)
        reg = get_trigger_registry()
        assert len(reg.list_names()) >= 1
        # Cleanup
        for name in reg.list_names():
            reg.unregister(name)

    def test_from_webhook_registers(self) -> None:
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        class _Stub:
            pass

        stub = _Stub()
        EIPMixin.from_webhook(stub, "/test")
        reg = get_trigger_registry()
        assert len(reg.list_names()) >= 1
        # Cleanup
        for name in reg.list_names():
            reg.unregister(name)
